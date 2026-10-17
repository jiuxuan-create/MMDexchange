# -*- coding: utf-8 -*-
"""PMX (Polygon Model eXtended) 2.0 / 2.1 读写内核 —— 纯标准库实现。

覆盖 PMX 规范的全部区块：
    头部 / 模型信息 / 顶点 / 面 / 纹理 / 材质 / 骨骼 / 表情 / 表示枠 / 刚体 / 关节

为什么不用现成库：
  * pymeshio 读不了带「追加UV」的真实 PMX 文件（会直接抛异常）
  * pymeshio 的写出器只实现了「顶点モーフ」，材质/骨骼/UV/グループモーフ全部未实现
本模块把这两块补齐，并且以语义化对象暴露数据，便于从 VRM 组装出 PMX。

坐标系约定（PMX）：左手系，Y 轴向上，贴图 UV 原点在左上角。

参考规范：PMX 2.0/2.1 仕様書（PMXEditor 同梱）
"""

import io
import os
import struct

__all__ = [
    "PmxModel", "PmxVertex", "PmxMaterial", "PmxBone", "PmxMorph",
    "PmxDisplaySlot", "PmxRigidBody", "PmxJoint",
    "Bdef1", "Bdef2", "Bdef4", "Sdef", "Qdef",
    "read_pmx", "read_pmx_bytes", "write_pmx", "write_pmx_bytes",
    "VEC3", "VEC4", "IDENTITY_ROT",
]

PMX_SIGNATURE = b"PMX "

# 头部「格納データ数」字节。PMXEditor 与 pymeshio 都写 8，读取时不做校验。
DEFAULT_DATA_FLAGS = 8

TEXT_UTF16 = 0
TEXT_UTF8 = 1

# ---------------------------------------------------------------- 位标记

# 骨骼标记（uint16）
BONEFLAG_TAIL_IS_BONE = 0x0001
BONEFLAG_CAN_ROTATE = 0x0002
BONEFLAG_CAN_TRANSLATE = 0x0004
BONEFLAG_IS_VISIBLE = 0x0008
BONEFLAG_CAN_MANIPULATE = 0x0010
BONEFLAG_IS_IK = 0x0020
BONEFLAG_LOCAL_APPEND = 0x0080
BONEFLAG_IS_EXTERNAL_ROTATION = 0x0100
BONEFLAG_IS_EXTERNAL_TRANSLATION = 0x0200
BONEFLAG_HAS_FIXED_AXIS = 0x0400
BONEFLAG_HAS_LOCAL_AXIS = 0x0800
BONEFLAG_IS_AFTER_PHYSICS_DEFORM = 0x1000
BONEFLAG_IS_EXTERNAL_PARENT_DEFORM = 0x2000

# 材质描画标记（uint8）
MATERIALFLAG_BOTHFACE = 0x01
MATERIALFLAG_GROUNDSHADOW = 0x02
MATERIALFLAG_SELFSHADOWMAP = 0x04
MATERIALFLAG_SELFSHADOW = 0x08
MATERIALFLAG_EDGE = 0x10

# スフィアモード
SPHERE_NONE = 0
SPHERE_MULT = 1
SPHERE_ADD = 2
SPHERE_SUBTEXTURE = 3

# 蒙皮类型
DEFORM_BDEF1 = 0
DEFORM_BDEF2 = 1
DEFORM_BDEF4 = 2
DEFORM_SDEF = 3
DEFORM_QDEF = 4

# 表情种类
MORPH_GROUP = 0
MORPH_VERTEX = 1
MORPH_BONE = 2
MORPH_UV = 3
MORPH_UV1 = 4
MORPH_UV2 = 5
MORPH_UV3 = 6
MORPH_UV4 = 7
MORPH_MATERIAL = 8
MORPH_FLIP = 9
MORPH_IMPULSE = 10

# 表情面板
PANEL_SYSTEM = 0
PANEL_BROW = 1
PANEL_EYE = 2
PANEL_MOUTH = 3
PANEL_OTHER = 4

# 刚体
SHAPE_SPHERE = 0
SHAPE_BOX = 1
SHAPE_CAPSULE = 2

RIGIDBODY_FOLLOW_BONE = 0
RIGIDBODY_PHYSICS = 1
RIGIDBODY_PHYSICS_BONE = 2

# 关节种类
JOINT_SPRING6DOF = 0
JOINT_6DOF = 1
JOINT_P2P = 2
JOINT_CONE_TWIST = 3
JOINT_SLIDER = 4
JOINT_HINGE = 5

VEC3 = (0.0, 0.0, 0.0)
VEC4 = (0.0, 0.0, 0.0, 0.0)
IDENTITY_ROT = (0.0, 0.0, 0.0)

_INDEX_FMT = {1: "b", 2: "h", 4: "i"}
_INDEX_UNSIGNED_FMT = {1: "B", 2: "H", 4: "I"}


# ---------------------------------------------------------------- 蒙皮数据


class Bdef1(object):
    __slots__ = ("index0",)
    kind = DEFORM_BDEF1

    def __init__(self, index0):
        self.index0 = index0

    def bones(self):
        return ((self.index0, 1.0),)


class Bdef2(object):
    __slots__ = ("index0", "index1", "weight0")
    kind = DEFORM_BDEF2

    def __init__(self, index0, index1, weight0):
        self.index0 = index0
        self.index1 = index1
        self.weight0 = weight0

    def bones(self):
        return ((self.index0, self.weight0), (self.index1, 1.0 - self.weight0))


class Bdef4(object):
    __slots__ = ("indices", "weights")
    kind = DEFORM_BDEF4

    def __init__(self, indices, weights):
        self.indices = tuple(indices)
        self.weights = tuple(weights)

    def bones(self):
        return tuple(zip(self.indices, self.weights))


class Qdef(Bdef4):
    """PMX 2.1 的 QDEF，双四元数蒙皮，数据结构与 BDEF4 相同。"""
    kind = DEFORM_QDEF


class Sdef(object):
    __slots__ = ("index0", "index1", "weight0", "c", "r0", "r1")
    kind = DEFORM_SDEF

    def __init__(self, index0, index1, weight0, c=VEC3, r0=VEC3, r1=VEC3):
        self.index0 = index0
        self.index1 = index1
        self.weight0 = weight0
        self.c = c
        self.r0 = r0
        self.r1 = r1

    def bones(self):
        return ((self.index0, self.weight0), (self.index1, 1.0 - self.weight0))


# ---------------------------------------------------------------- 数据类


class PmxVertex(object):
    __slots__ = ("position", "normal", "uv", "additional_uv",
                 "deform", "edge_factor")

    def __init__(self, position=VEC3, normal=(0.0, 1.0, 0.0), uv=(0.0, 0.0),
                 additional_uv=(), deform=None, edge_factor=1.0):
        self.position = position
        self.normal = normal
        self.uv = uv
        self.additional_uv = list(additional_uv)
        self.deform = deform if deform is not None else Bdef1(0)
        self.edge_factor = edge_factor


class PmxMaterial(object):
    __slots__ = ("name", "english_name", "diffuse", "specular",
                 "specular_factor", "ambient", "flag", "edge_color",
                 "edge_size", "texture_index", "sphere_texture_index",
                 "sphere_mode", "toon_sharing_flag", "toon_texture_index",
                 "comment", "index_count")

    def __init__(self, name="material", english_name="", diffuse=(1, 1, 1, 1),
                 specular=(0, 0, 0), specular_factor=0.0, ambient=(0.5, 0.5, 0.5),
                 flag=MATERIALFLAG_GROUNDSHADOW | MATERIALFLAG_SELFSHADOWMAP
                 | MATERIALFLAG_SELFSHADOW | MATERIALFLAG_EDGE,
                 edge_color=(0, 0, 0, 1), edge_size=1.0, texture_index=-1,
                 sphere_texture_index=-1, sphere_mode=SPHERE_NONE,
                 toon_sharing_flag=1, toon_texture_index=0, comment="",
                 index_count=0):
        self.name = name
        self.english_name = english_name
        self.diffuse = diffuse
        self.specular = specular
        self.specular_factor = specular_factor
        self.ambient = ambient
        self.flag = flag
        self.edge_color = edge_color
        self.edge_size = edge_size
        self.texture_index = texture_index
        self.sphere_texture_index = sphere_texture_index
        self.sphere_mode = sphere_mode
        self.toon_sharing_flag = toon_sharing_flag
        self.toon_texture_index = toon_texture_index
        self.comment = comment
        self.index_count = index_count


class PmxBone(object):
    __slots__ = ("name", "english_name", "position", "parent_index", "layer",
                 "flag", "tail_position", "tail_index", "effect_index",
                 "effect_factor", "fixed_axis", "local_x_axis", "local_z_axis",
                 "external_key", "ik")

    def __init__(self, name="bone", english_name="", position=VEC3,
                 parent_index=-1, layer=0,
                 flag=BONEFLAG_CAN_ROTATE | BONEFLAG_CAN_TRANSLATE
                 | BONEFLAG_IS_VISIBLE | BONEFLAG_CAN_MANIPULATE,
                 tail_position=VEC3, tail_index=-1, effect_index=-1,
                 effect_factor=0.0, fixed_axis=VEC3, local_x_axis=(1, 0, 0),
                 local_z_axis=(0, 0, 1), external_key=0, ik=None):
        self.name = name
        self.english_name = english_name
        self.position = position
        self.parent_index = parent_index
        self.layer = layer
        self.flag = flag
        self.tail_position = tail_position
        self.tail_index = tail_index
        self.effect_index = effect_index
        self.effect_factor = effect_factor
        self.fixed_axis = fixed_axis
        self.local_x_axis = local_x_axis
        self.local_z_axis = local_z_axis
        self.external_key = external_key
        self.ik = ik

    @property
    def tail_is_bone(self):
        return bool(self.flag & BONEFLAG_TAIL_IS_BONE)

    @property
    def is_ik(self):
        return bool(self.flag & BONEFLAG_IS_IK)

    @property
    def has_append(self):
        return bool(self.flag & (BONEFLAG_IS_EXTERNAL_ROTATION
                                 | BONEFLAG_IS_EXTERNAL_TRANSLATION))


class PmxIkLink(object):
    __slots__ = ("bone_index", "limit_angle", "limit_min", "limit_max")

    def __init__(self, bone_index, limit_angle=0, limit_min=VEC3, limit_max=VEC3):
        self.bone_index = bone_index
        self.limit_angle = limit_angle
        self.limit_min = limit_min
        self.limit_max = limit_max


class PmxIk(object):
    __slots__ = ("target_index", "loop", "limit_radian", "links")

    def __init__(self, target_index=-1, loop=1, limit_radian=0.0, links=None):
        self.target_index = target_index
        self.loop = loop
        self.limit_radian = limit_radian
        self.links = list(links) if links else []


class MorphGroupOffset(object):
    __slots__ = ("index", "ratio")

    def __init__(self, index, ratio):
        self.index = index
        self.ratio = ratio


class MorphVertexOffset(object):
    __slots__ = ("index", "offset")

    def __init__(self, index, offset):
        self.index = index
        self.offset = offset


class MorphBoneOffset(object):
    __slots__ = ("index", "translation", "rotation")

    def __init__(self, index, translation=VEC3, rotation=(0, 0, 0, 1)):
        self.index = index
        self.translation = translation
        self.rotation = rotation


class MorphUvOffset(object):
    __slots__ = ("index", "offset")

    def __init__(self, index, offset=VEC4):
        self.index = index
        self.offset = offset


class MorphMaterialOffset(object):
    __slots__ = ("index", "calc_mode", "diffuse", "specular",
                 "specular_factor", "ambient", "edge_color", "edge_size",
                 "texture_factor", "sphere_texture_factor", "toon_texture_factor")

    def __init__(self, index, calc_mode=0, diffuse=(0, 0, 0, 0),
                 specular=(0, 0, 0), specular_factor=0.0, ambient=(0, 0, 0),
                 edge_color=(0, 0, 0, 0), edge_size=0.0,
                 texture_factor=(0, 0, 0, 0), sphere_texture_factor=(0, 0, 0, 0),
                 toon_texture_factor=(0, 0, 0, 0)):
        self.index = index
        self.calc_mode = calc_mode
        self.diffuse = diffuse
        self.specular = specular
        self.specular_factor = specular_factor
        self.ambient = ambient
        self.edge_color = edge_color
        self.edge_size = edge_size
        self.texture_factor = texture_factor
        self.sphere_texture_factor = sphere_texture_factor
        self.toon_texture_factor = toon_texture_factor


class MorphFlipOffset(object):
    __slots__ = ("index", "ratio")

    def __init__(self, index, ratio):
        self.index = index
        self.ratio = ratio


class MorphImpulseOffset(object):
    __slots__ = ("index", "local_flag", "velocity", "torque")

    def __init__(self, index, local_flag=0, velocity=VEC3, torque=VEC3):
        self.index = index
        self.local_flag = local_flag
        self.velocity = velocity
        self.torque = torque


class PmxMorph(object):
    __slots__ = ("name", "english_name", "panel", "morph_type", "offsets")

    def __init__(self, name="morph", english_name="", panel=PANEL_OTHER,
                 morph_type=MORPH_VERTEX, offsets=None):
        self.name = name
        self.english_name = english_name
        self.panel = panel
        self.morph_type = morph_type
        self.offsets = list(offsets) if offsets else []


class PmxDisplaySlot(object):
    __slots__ = ("name", "english_name", "special_flag", "references")

    def __init__(self, name="frame", english_name="", special_flag=0,
                 references=None):
        self.name = name
        self.english_name = english_name
        self.special_flag = special_flag
        # 每个元素是 (0, 骨骼index) 或 (1, 表情index)
        self.references = list(references) if references else []


class PmxRigidBody(object):
    __slots__ = ("name", "english_name", "bone_index", "collision_group",
                 "no_collision_group", "shape_type", "shape_size",
                 "shape_position", "shape_rotation", "mass", "linear_damping",
                 "angular_damping", "restitution", "friction", "mode")

    def __init__(self, name="rigidbody", english_name="", bone_index=-1,
                 collision_group=0, no_collision_group=0,
                 shape_type=SHAPE_SPHERE, shape_size=(0.5, 0.0, 0.0),
                 shape_position=VEC3, shape_rotation=IDENTITY_ROT,
                 mass=1.0, linear_damping=0.5, angular_damping=0.5,
                 restitution=0.0, friction=0.5, mode=RIGIDBODY_PHYSICS):
        self.name = name
        self.english_name = english_name
        self.bone_index = bone_index
        self.collision_group = collision_group
        self.no_collision_group = no_collision_group
        self.shape_type = shape_type
        self.shape_size = shape_size
        self.shape_position = shape_position
        self.shape_rotation = shape_rotation
        self.mass = mass
        self.linear_damping = linear_damping
        self.angular_damping = angular_damping
        self.restitution = restitution
        self.friction = friction
        self.mode = mode


class PmxJoint(object):
    __slots__ = ("name", "english_name", "joint_type", "rigidbody_index_a",
                 "rigidbody_index_b", "position", "rotation",
                 "translation_limit_min", "translation_limit_max",
                 "rotation_limit_min", "rotation_limit_max",
                 "spring_constant_translation", "spring_constant_rotation")

    def __init__(self, name="joint", english_name="",
                 joint_type=JOINT_SPRING6DOF, rigidbody_index_a=-1,
                 rigidbody_index_b=-1, position=VEC3, rotation=IDENTITY_ROT,
                 translation_limit_min=VEC3, translation_limit_max=VEC3,
                 rotation_limit_min=VEC3, rotation_limit_max=VEC3,
                 spring_constant_translation=VEC3,
                 spring_constant_rotation=VEC3):
        self.name = name
        self.english_name = english_name
        self.joint_type = joint_type
        self.rigidbody_index_a = rigidbody_index_a
        self.rigidbody_index_b = rigidbody_index_b
        self.position = position
        self.rotation = rotation
        self.translation_limit_min = translation_limit_min
        self.translation_limit_max = translation_limit_max
        self.rotation_limit_min = rotation_limit_min
        self.rotation_limit_max = rotation_limit_max
        self.spring_constant_translation = spring_constant_translation
        self.spring_constant_rotation = spring_constant_rotation


class PmxModel(object):
    """PMX 模型的语义化容器。"""

    def __init__(self, version=2.0, name="model", english_name="",
                 comment="", english_comment="", text_encoding=TEXT_UTF16,
                 additional_uv_count=0, data_flags=DEFAULT_DATA_FLAGS):
        self.version = version
        self.name = name
        self.english_name = english_name
        self.comment = comment
        self.english_comment = english_comment
        self.text_encoding = text_encoding
        self.additional_uv_count = additional_uv_count
        self.data_flags = data_flags
        self.vertices = []
        self.indices = []
        self.textures = []
        self.materials = []
        self.bones = []
        self.morphs = []
        self.display_slots = []
        self.rigidbodies = []
        self.joints = []

    def __repr__(self):
        return "<PmxModel v%s %r %dverts %dbones %dmorphs %dmat %drb %djoint>" % (
            self.version, self.name, len(self.vertices), len(self.bones),
            len(self.morphs), len(self.materials), len(self.rigidbodies),
            len(self.joints))

    def bone_index(self, name):
        for i, b in enumerate(self.bones):
            if b.name == name:
                return i
        return -1

    def morph_index(self, name):
        for i, m in enumerate(self.morphs):
            if m.name == name:
                return i
        return -1


# ---------------------------------------------------------------- 读取


class PmxReadError(Exception):
    pass


class _ByteReader(object):
    __slots__ = ("data", "pos", "text_encoding", "additional_uv_count")

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.text_encoding = TEXT_UTF16
        self.additional_uv_count = 0

    def read(self, n):
        end = self.pos + n
        if end > len(self.data):
            raise PmxReadError("PMX 数据在偏移 %d 处意外结束（需要 %d 字节）"
                               % (self.pos, n))
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def uint8(self):
        return self.read(1)[0]

    def int8(self):
        return struct.unpack_from("<b", self.read(1))[0]

    def uint16(self):
        return struct.unpack_from("<H", self.read(2))[0]

    def int32(self):
        return struct.unpack_from("<i", self.read(4))[0]

    def uint32(self):
        return struct.unpack_from("<I", self.read(4))[0]

    def float32(self):
        return struct.unpack_from("<f", self.read(4))[0]

    def vec2(self):
        return struct.unpack_from("<2f", self.read(8))

    def vec3(self):
        return struct.unpack_from("<3f", self.read(12))

    def vec4(self):
        return struct.unpack_from("<4f", self.read(16))

    def index(self, size):
        fmt = _INDEX_FMT.get(size)
        if fmt is None:
            raise PmxReadError("非法的索引宽度 %r" % (size,))
        return struct.unpack_from("<" + fmt, self.read(size))[0]

    def vertex_index(self, size):
        fmt = _INDEX_UNSIGNED_FMT.get(size)
        if fmt is None:
            raise PmxReadError("非法的顶点索引宽度 %r" % (size,))
        return struct.unpack_from("<" + fmt, self.read(size))[0]

    def text(self):
        length = self.int32()
        if length < 0:
            raise PmxReadError("文本长度非法: %d" % length)
        raw = self.read(length)
        if self.text_encoding == TEXT_UTF16:
            return raw.decode("utf-16-le", errors="replace")
        return raw.decode("utf-8", errors="replace")


def _read_vertex(r, deform_size, uv_count):
    position = r.vec3()
    normal = r.vec3()
    uv = r.vec2()
    additional_uv = [r.vec4() for _ in range(uv_count)]
    kind = r.uint8()
    if kind == DEFORM_BDEF1:
        deform = Bdef1(r.index(deform_size))
    elif kind == DEFORM_BDEF2:
        i0 = r.index(deform_size)
        i1 = r.index(deform_size)
        deform = Bdef2(i0, i1, r.float32())
    elif kind == DEFORM_BDEF4:
        indices = [r.index(deform_size) for _ in range(4)]
        weights = [r.float32() for _ in range(4)]
        deform = Bdef4(indices, weights)
    elif kind == DEFORM_SDEF:
        i0 = r.index(deform_size)
        i1 = r.index(deform_size)
        w0 = r.float32()
        c = r.vec3()
        r0 = r.vec3()
        r1 = r.vec3()
        deform = Sdef(i0, i1, w0, c, r0, r1)
    elif kind == DEFORM_QDEF:
        indices = [r.index(deform_size) for _ in range(4)]
        weights = [r.float32() for _ in range(4)]
        deform = Qdef(indices, weights)
    else:
        raise PmxReadError("未知的蒙皮类型 %d" % kind)
    edge_factor = r.float32()
    return PmxVertex(position, normal, uv, additional_uv, deform, edge_factor)


def _read_material(r, tex_size):
    name = r.text()
    english_name = r.text()
    diffuse = r.vec4()
    specular = r.vec3()
    specular_factor = r.float32()
    ambient = r.vec3()
    flag = r.uint8()
    edge_color = r.vec4()
    edge_size = r.float32()
    texture_index = r.index(tex_size)
    sphere_texture_index = r.index(tex_size)
    sphere_mode = r.uint8()
    toon_sharing_flag = r.uint8()
    if toon_sharing_flag == 0:
        toon_texture_index = r.index(tex_size)
    else:
        toon_texture_index = r.uint8()
    comment = r.text()
    index_count = r.int32()
    return PmxMaterial(name, english_name, diffuse, specular, specular_factor,
                       ambient, flag, edge_color, edge_size, texture_index,
                       sphere_texture_index, sphere_mode, toon_sharing_flag,
                       toon_texture_index, comment, index_count)


def _read_bone(r, bone_size):
    name = r.text()
    english_name = r.text()
    position = r.vec3()
    parent_index = r.index(bone_size)
    layer = r.int32()
    flag = r.uint16()

    tail_position = VEC3
    tail_index = -1
    if flag & BONEFLAG_TAIL_IS_BONE:
        tail_index = r.index(bone_size)
    else:
        tail_position = r.vec3()

    effect_index = -1
    effect_factor = 0.0
    if flag & (BONEFLAG_IS_EXTERNAL_ROTATION | BONEFLAG_IS_EXTERNAL_TRANSLATION):
        effect_index = r.index(bone_size)
        effect_factor = r.float32()

    fixed_axis = VEC3
    if flag & BONEFLAG_HAS_FIXED_AXIS:
        fixed_axis = r.vec3()

    local_x_axis, local_z_axis = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    if flag & BONEFLAG_HAS_LOCAL_AXIS:
        local_x_axis = r.vec3()
        local_z_axis = r.vec3()

    external_key = 0
    if flag & BONEFLAG_IS_EXTERNAL_PARENT_DEFORM:
        external_key = r.int32()

    ik = None
    if flag & BONEFLAG_IS_IK:
        target_index = r.index(bone_size)
        loop = r.int32()
        limit_radian = r.float32()
        link_count = r.int32()
        if link_count < 0:
            raise PmxReadError("IK リンク数非法: %d" % link_count)
        links = []
        for _ in range(link_count):
            bone_index = r.index(bone_size)
            limit_angle = r.uint8()
            if limit_angle == 1:
                links.append(PmxIkLink(bone_index, 1, r.vec3(), r.vec3()))
            else:
                links.append(PmxIkLink(bone_index, 0))
        ik = PmxIk(target_index, loop, limit_radian, links)

    return PmxBone(name, english_name, position, parent_index, layer, flag,
                   tail_position, tail_index, effect_index, effect_factor,
                   fixed_axis, local_x_axis, local_z_axis, external_key, ik)


def _read_morph(r, vertex_size, bone_size, morph_size, material_size,
                rigidbody_size, uv_count):
    name = r.text()
    english_name = r.text()
    panel = r.uint8()
    morph_type = r.uint8()
    count = r.int32()
    if count < 0:
        raise PmxReadError("表情偏移数非法: %d" % count)
    offsets = []
    if morph_type == MORPH_GROUP:
        for _ in range(count):
            offsets.append(MorphGroupOffset(r.index(morph_size), r.float32()))
    elif morph_type == MORPH_VERTEX:
        for _ in range(count):
            offsets.append(MorphVertexOffset(r.vertex_index(vertex_size), r.vec3()))
    elif morph_type == MORPH_BONE:
        for _ in range(count):
            offsets.append(MorphBoneOffset(r.index(bone_size), r.vec3(), r.vec4()))
    elif morph_type in (MORPH_UV, MORPH_UV1, MORPH_UV2, MORPH_UV3, MORPH_UV4):
        for _ in range(count):
            offsets.append(MorphUvOffset(r.vertex_index(vertex_size), r.vec4()))
    elif morph_type == MORPH_MATERIAL:
        for _ in range(count):
            index = r.index(material_size)
            calc_mode = r.uint8()
            diffuse = r.vec4()
            specular = r.vec3()
            specular_factor = r.float32()
            ambient = r.vec3()
            edge_color = r.vec4()
            edge_size = r.float32()
            texture_factor = r.vec4()
            sphere_factor = r.vec4()
            toon_factor = r.vec4()
            offsets.append(MorphMaterialOffset(
                index, calc_mode, diffuse, specular, specular_factor, ambient,
                edge_color, edge_size, texture_factor, sphere_factor, toon_factor))
    elif morph_type == MORPH_FLIP:
        for _ in range(count):
            offsets.append(MorphFlipOffset(r.index(morph_size), r.float32()))
    elif morph_type == MORPH_IMPULSE:
        for _ in range(count):
            index = r.index(rigidbody_size)
            local_flag = r.uint8()
            offsets.append(MorphImpulseOffset(index, local_flag, r.vec3(), r.vec3()))
    else:
        raise PmxReadError("未知的表情种类 %d" % morph_type)
    return PmxMorph(name, english_name, panel, morph_type, offsets)


def _read_display_slot(r, bone_size, morph_size):
    name = r.text()
    english_name = r.text()
    special_flag = r.uint8()
    count = r.int32()
    if count < 0:
        raise PmxReadError("表示枠要素数非法: %d" % count)
    references = []
    for _ in range(count):
        target = r.uint8()
        if target == 0:
            references.append((0, r.index(bone_size)))
        elif target == 1:
            references.append((1, r.index(morph_size)))
        else:
            raise PmxReadError("未知的表示枠要素类型 %d" % target)
    return PmxDisplaySlot(name, english_name, special_flag, references)


def _read_rigidbody(r, bone_size):
    name = r.text()
    english_name = r.text()
    bone_index = r.index(bone_size)
    collision_group = r.uint8()
    no_collision_group = r.uint16()
    shape_type = r.uint8()
    shape_size = r.vec3()
    shape_position = r.vec3()
    shape_rotation = r.vec3()
    mass = r.float32()
    linear_damping = r.float32()
    angular_damping = r.float32()
    restitution = r.float32()
    friction = r.float32()
    mode = r.uint8()
    return PmxRigidBody(name, english_name, bone_index, collision_group,
                        no_collision_group, shape_type, shape_size,
                        shape_position, shape_rotation, mass, linear_damping,
                        angular_damping, restitution, friction, mode)


def _read_joint(r, rigidbody_size):
    name = r.text()
    english_name = r.text()
    joint_type = r.uint8()
    rb_a = r.index(rigidbody_size)
    rb_b = r.index(rigidbody_size)
    position = r.vec3()
    rotation = r.vec3()
    trans_min = r.vec3()
    trans_max = r.vec3()
    rot_min = r.vec3()
    rot_max = r.vec3()
    spring_trans = r.vec3()
    spring_rot = r.vec3()
    return PmxJoint(name, english_name, joint_type, rb_a, rb_b, position,
                    rotation, trans_min, trans_max, rot_min, rot_max,
                    spring_trans, spring_rot)


def read_pmx_bytes(data):
    """从字节串解析 PMX，返回 PmxModel。"""
    r = _ByteReader(data)
    if r.read(4) != PMX_SIGNATURE:
        raise PmxReadError("不是 PMX 文件（文件头不是 'PMX '）")
    version = struct.unpack_from("<f", r.read(4))[0]
    data_flags = r.uint8()
    text_encoding = r.uint8()
    additional_uv_count = r.uint8()
    vertex_index_size = r.uint8()
    texture_index_size = r.uint8()
    material_index_size = r.uint8()
    bone_index_size = r.uint8()
    morph_index_size = r.uint8()
    rigidbody_index_size = r.uint8()

    r.text_encoding = text_encoding
    r.additional_uv_count = additional_uv_count

    model = PmxModel(version=version, text_encoding=text_encoding,
                     additional_uv_count=additional_uv_count,
                     data_flags=data_flags)
    model.name = r.text()
    model.english_name = r.text()
    model.comment = r.text()
    model.english_comment = r.text()

    vcount = r.int32()
    if vcount < 0:
        raise PmxReadError("顶点数非法: %d" % vcount)
    model.vertices = [_read_vertex(r, bone_index_size, additional_uv_count)
                      for _ in range(vcount)]

    icount = r.int32()
    if icount < 0:
        raise PmxReadError("索引数非法: %d" % icount)
    model.indices = [r.vertex_index(vertex_index_size) for _ in range(icount)]

    tcount = r.int32()
    if tcount < 0:
        raise PmxReadError("纹理数非法: %d" % tcount)
    model.textures = [r.text() for _ in range(tcount)]

    mcount = r.int32()
    if mcount < 0:
        raise PmxReadError("材质数非法: %d" % mcount)
    model.materials = [_read_material(r, texture_index_size) for _ in range(mcount)]

    bcount = r.int32()
    if bcount < 0:
        raise PmxReadError("骨骼数非法: %d" % bcount)
    model.bones = [_read_bone(r, bone_index_size) for _ in range(bcount)]

    mocount = r.int32()
    if mocount < 0:
        raise PmxReadError("表情数非法: %d" % mocount)
    model.morphs = [_read_morph(r, vertex_index_size, bone_index_size,
                                morph_index_size, material_index_size,
                                rigidbody_index_size, additional_uv_count)
                    for _ in range(mocount)]

    dcount = r.int32()
    if dcount < 0:
        raise PmxReadError("表示枠数非法: %d" % dcount)
    model.display_slots = [_read_display_slot(r, bone_index_size, morph_index_size)
                           for _ in range(dcount)]

    rcount = r.int32()
    if rcount < 0:
        raise PmxReadError("刚体数非法: %d" % rcount)
    model.rigidbodies = [_read_rigidbody(r, bone_index_size) for _ in range(rcount)]

    jcount = r.int32()
    if jcount < 0:
        raise PmxReadError("关节数非法: %d" % jcount)
    model.joints = [_read_joint(r, rigidbody_index_size) for _ in range(jcount)]

    return model


def read_pmx(path):
    """读取 .pmx 文件。"""
    with io.open(path, "rb") as f:
        return read_pmx_bytes(f.read())


# ---------------------------------------------------------------- 写出


class _ByteWriter(object):
    __slots__ = ("buf", "text_encoding")

    def __init__(self, text_encoding=TEXT_UTF16):
        self.buf = bytearray()
        self.text_encoding = text_encoding

    def write(self, fmt, *values):
        self.buf.extend(struct.pack("<" + fmt, *values))

    def uint8(self, v):
        self.buf.append(int(v) & 0xFF)

    def int32(self, v):
        self.buf.extend(struct.pack("<i", int(v)))

    def uint16(self, v):
        self.buf.extend(struct.pack("<H", int(v) & 0xFFFF))

    def float32(self, v):
        self.buf.extend(struct.pack("<f", float(v)))

    def vec2(self, v):
        self.buf.extend(struct.pack("<2f", float(v[0]), float(v[1])))

    def vec3(self, v):
        self.buf.extend(struct.pack("<3f", float(v[0]), float(v[1]), float(v[2])))

    def vec4(self, v):
        self.buf.extend(struct.pack("<4f", float(v[0]), float(v[1]),
                                    float(v[2]), float(v[3])))

    def index(self, size, v):
        self.buf.extend(struct.pack("<" + _INDEX_FMT[size], int(v)))

    def vertex_index(self, size, v):
        self.buf.extend(struct.pack("<" + _INDEX_UNSIGNED_FMT[size], int(v)))

    def text(self, s):
        if not s:
            self.int32(0)
            return
        if self.text_encoding == TEXT_UTF16:
            raw = s.encode("utf-16-le")
        else:
            raw = s.encode("utf-8")
        self.int32(len(raw))
        self.buf.extend(raw)


def _index_size(count):
    """按 PMX 惯例选择索引宽度（有符号安全，-1 必须可表示）。"""
    if count < 128:
        return 1
    if count < 32768:
        return 2
    return 4


def write_pmx_bytes(model, text_encoding=None, version=None):
    """把 PmxModel 序列化为 PMX 字节串。"""
    if text_encoding is None:
        text_encoding = model.text_encoding
    if version is None:
        version = model.version

    vertex_index_size = _index_size(len(model.vertices))
    texture_index_size = _index_size(len(model.textures))
    material_index_size = _index_size(len(model.materials))
    bone_index_size = _index_size(len(model.bones))
    morph_index_size = _index_size(len(model.morphs))
    rigidbody_index_size = _index_size(len(model.rigidbodies))

    w = _ByteWriter(text_encoding)
    w.buf.extend(PMX_SIGNATURE)
    w.float32(version)
    w.uint8(model.data_flags if model.data_flags else DEFAULT_DATA_FLAGS)
    w.uint8(text_encoding)
    uv_count = len(model.vertices[0].additional_uv) if model.vertices else 0
    w.uint8(uv_count)
    w.uint8(vertex_index_size)
    w.uint8(texture_index_size)
    w.uint8(material_index_size)
    w.uint8(bone_index_size)
    w.uint8(morph_index_size)
    w.uint8(rigidbody_index_size)

    w.text(model.name)
    w.text(model.english_name)
    w.text(model.comment)
    w.text(model.english_comment)

    # 顶点
    w.int32(len(model.vertices))
    for v in model.vertices:
        w.vec3(v.position)
        w.vec3(v.normal)
        w.vec2(v.uv)
        for auv in v.additional_uv:
            w.vec4(auv)
        d = v.deform
        w.uint8(d.kind)
        if d.kind == DEFORM_BDEF1:
            w.index(bone_index_size, d.index0)
        elif d.kind == DEFORM_BDEF2:
            w.index(bone_index_size, d.index0)
            w.index(bone_index_size, d.index1)
            w.float32(d.weight0)
        elif d.kind in (DEFORM_BDEF4, DEFORM_QDEF):
            for idx in d.indices:
                w.index(bone_index_size, idx)
            for weight in d.weights:
                w.float32(weight)
        elif d.kind == DEFORM_SDEF:
            w.index(bone_index_size, d.index0)
            w.index(bone_index_size, d.index1)
            w.float32(d.weight0)
            w.vec3(d.c)
            w.vec3(d.r0)
            w.vec3(d.r1)
        else:
            raise ValueError("不支持的蒙皮类型: %r" % (d.kind,))
        w.float32(v.edge_factor)

    # 面
    w.int32(len(model.indices))
    for i in model.indices:
        w.vertex_index(vertex_index_size, i)

    # 纹理
    w.int32(len(model.textures))
    for t in model.textures:
        w.text(t)

    # 材质
    w.int32(len(model.materials))
    for m in model.materials:
        w.text(m.name)
        w.text(m.english_name)
        w.vec4(m.diffuse)
        w.vec3(m.specular)
        w.float32(m.specular_factor)
        w.vec3(m.ambient)
        w.uint8(m.flag)
        w.vec4(m.edge_color)
        w.float32(m.edge_size)
        w.index(texture_index_size, m.texture_index)
        w.index(texture_index_size, m.sphere_texture_index)
        w.uint8(m.sphere_mode)
        w.uint8(m.toon_sharing_flag)
        if m.toon_sharing_flag == 0:
            w.index(texture_index_size, m.toon_texture_index)
        else:
            w.uint8(m.toon_texture_index)
        w.text(m.comment)
        w.int32(m.index_count)

    # 骨骼
    w.int32(len(model.bones))
    for b in model.bones:
        w.text(b.name)
        w.text(b.english_name)
        w.vec3(b.position)
        w.index(bone_index_size, b.parent_index)
        w.int32(b.layer)
        w.uint16(b.flag)
        if b.flag & BONEFLAG_TAIL_IS_BONE:
            w.index(bone_index_size, b.tail_index)
        else:
            w.vec3(b.tail_position)
        if b.flag & (BONEFLAG_IS_EXTERNAL_ROTATION | BONEFLAG_IS_EXTERNAL_TRANSLATION):
            w.index(bone_index_size, b.effect_index)
            w.float32(b.effect_factor)
        if b.flag & BONEFLAG_HAS_FIXED_AXIS:
            w.vec3(b.fixed_axis)
        if b.flag & BONEFLAG_HAS_LOCAL_AXIS:
            w.vec3(b.local_x_axis)
            w.vec3(b.local_z_axis)
        if b.flag & BONEFLAG_IS_EXTERNAL_PARENT_DEFORM:
            w.int32(b.external_key)
        if b.flag & BONEFLAG_IS_IK:
            ik = b.ik
            if ik is None:
                raise ValueError("骨骼 %r 标记为 IK 但缺少 IK 数据" % b.name)
            w.index(bone_index_size, ik.target_index)
            w.int32(ik.loop)
            w.float32(ik.limit_radian)
            w.int32(len(ik.links))
            for link in ik.links:
                w.index(bone_index_size, link.bone_index)
                w.uint8(link.limit_angle)
                if link.limit_angle == 1:
                    w.vec3(link.limit_min)
                    w.vec3(link.limit_max)

    # 表情
    w.int32(len(model.morphs))
    for mo in model.morphs:
        w.text(mo.name)
        w.text(mo.english_name)
        w.uint8(mo.panel)
        w.uint8(mo.morph_type)
        w.int32(len(mo.offsets))
        for o in mo.offsets:
            if mo.morph_type == MORPH_GROUP:
                w.index(morph_index_size, o.index)
                w.float32(o.ratio)
            elif mo.morph_type == MORPH_VERTEX:
                w.vertex_index(vertex_index_size, o.index)
                w.vec3(o.offset)
            elif mo.morph_type == MORPH_BONE:
                w.index(bone_index_size, o.index)
                w.vec3(o.translation)
                w.vec4(o.rotation)
            elif mo.morph_type in (MORPH_UV, MORPH_UV1, MORPH_UV2, MORPH_UV3, MORPH_UV4):
                w.vertex_index(vertex_index_size, o.index)
                w.vec4(o.offset)
            elif mo.morph_type == MORPH_MATERIAL:
                w.index(material_index_size, o.index)
                w.uint8(o.calc_mode)
                w.vec4(o.diffuse)
                w.vec3(o.specular)
                w.float32(o.specular_factor)
                w.vec3(o.ambient)
                w.vec4(o.edge_color)
                w.float32(o.edge_size)
                w.vec4(o.texture_factor)
                w.vec4(o.sphere_texture_factor)
                w.vec4(o.toon_texture_factor)
            elif mo.morph_type == MORPH_FLIP:
                w.index(morph_index_size, o.index)
                w.float32(o.ratio)
            elif mo.morph_type == MORPH_IMPULSE:
                w.index(rigidbody_index_size, o.index)
                w.uint8(o.local_flag)
                w.vec3(o.velocity)
                w.vec3(o.torque)
            else:
                raise ValueError("不支持的表情种类: %r" % (mo.morph_type,))

    # 表示枠
    w.int32(len(model.display_slots))
    for s in model.display_slots:
        w.text(s.name)
        w.text(s.english_name)
        w.uint8(s.special_flag)
        w.int32(len(s.references))
        for kind, index in s.references:
            w.uint8(kind)
            if kind == 0:
                w.index(bone_index_size, index)
            elif kind == 1:
                w.index(morph_index_size, index)
            else:
                raise ValueError("未知的表示枠要素类型: %r" % (kind,))

    # 刚体
    w.int32(len(model.rigidbodies))
    for rb in model.rigidbodies:
        w.text(rb.name)
        w.text(rb.english_name)
        w.index(bone_index_size, rb.bone_index)
        w.uint8(rb.collision_group)
        w.uint16(rb.no_collision_group)
        w.uint8(rb.shape_type)
        w.vec3(rb.shape_size)
        w.vec3(rb.shape_position)
        w.vec3(rb.shape_rotation)
        w.float32(rb.mass)
        w.float32(rb.linear_damping)
        w.float32(rb.angular_damping)
        w.float32(rb.restitution)
        w.float32(rb.friction)
        w.uint8(rb.mode)

    # 关节
    w.int32(len(model.joints))
    for j in model.joints:
        w.text(j.name)
        w.text(j.english_name)
        w.uint8(j.joint_type)
        w.index(rigidbody_index_size, j.rigidbody_index_a)
        w.index(rigidbody_index_size, j.rigidbody_index_b)
        w.vec3(j.position)
        w.vec3(j.rotation)
        w.vec3(j.translation_limit_min)
        w.vec3(j.translation_limit_max)
        w.vec3(j.rotation_limit_min)
        w.vec3(j.rotation_limit_max)
        w.vec3(j.spring_constant_translation)
        w.vec3(j.spring_constant_rotation)

    return bytes(w.buf)


def write_pmx(path, model, text_encoding=None, version=None):
    """写出 .pmx 文件，返回写入字节数。"""
    data = write_pmx_bytes(model, text_encoding=text_encoding, version=version)
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "wb") as f:
        f.write(data)
    return len(data)
