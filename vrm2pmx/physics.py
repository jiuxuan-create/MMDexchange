# -*- coding: utf-8 -*-
"""物理转换：VRM SpringBone / 碰撞体 -> PMX 剛体 + ジョイント。

约定的依据（tools/probe_rigid_rotation.py 实测参考模型 106 个胶囊刚体）：
  * 刚体位置 = 骨骼段中点；shape_size = (半径, 段长, 0)；胶囊长轴 = 局部 +Y
  * 刚体旋转的欧拉角组合为 R = Rx·Ry·Rz（先绕 Z 转，再绕 Y，最后绕 X），
    吻合度 0.95（其它顺序 0.92~0.94，且不改变"必须是局部 Y 轴"这一结论）

MMD 碰撞分组安排：
  * 组 1 放 VRM 的碰撞体（身体），它们只与各组链碰撞，彼此不碰
  * 各条链独占一个组（2 起），链内自撞被关掉、链与链之间也不碰，
    只与组 1 的身体碰撞体相互作用 —— 这是 MMD 模型里最稳的常见做法
"""

import math

from . import pmx_model as P

__all__ = ["build_physics", "auto_generate_chains", "SPRING_KEYWORDS"]

# 自动生成物理时识别的骨骼关键词（VRM 里没有 SpringBone 时才用）
SPRING_KEYWORDS = [
    ("hair", ("hair", "\u9aea", "\u6bdb")),
    ("skirt", ("skirt", "\u30b9\u30ab\u30fc\u30c8", "\u88d9", "\u88d9\u5b50", "\u88d9\u6446")),
    ("tail", ("tail", "\u5c3b", "\u5c3e\u5df4")),
    ("ribbon", ("ribbon", "\u30ea\u30dc\u30f3", "\u8776\u7ed3")),
    ("sleeve", ("sleeve", "\u8896", "\u8896\u5b50")),
    ("scarf", ("scarf", "\u30de\u30d5\u30e9\u30fc", "\u56f4\u5dfe")),
    ("cape", ("cape", "\u30b1\u30fc\u30d7", "\u62ab\u98ce")),
    ("tie", ("tie", "\u30cd\u30af\u30bf\u30a4", "\u9886\u5e26")),
    ("ahoge", ("ahoge", "\u30a2\u30db\u51e0", "\u5446\u6bdb")),
]

BODY_GROUP = 1
FIRST_CHAIN_GROUP = 2
MAX_GROUP = 15


def euler_for_direction(d):
    """求 (rx, ry, rz) 使 Rx·Ry·Rz 把 (0,1,0) 转到方向 d。"""
    n = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    dx, dy, dz = d[0] / n, d[1] / n, d[2] / n
    dx = max(-1.0, min(1.0, dx))
    rz = -math.asin(dx)
    cos_rz = math.cos(rz)
    if abs(cos_rz) < 1e-9:
        rx = 0.0
    else:
        rx = math.atan2(dz, dy)
    return (rx, 0.0, rz)


def _dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


class PhysicsBuilder(object):
    def __init__(self, vrm, bones, transform, options=None):
        self.vrm = vrm
        self.bones = bones
        self.doc = transform.doc
        self.transform = transform
        self.options = options or {}
        self.rigidbodies = []
        self.joints = []
        self.warnings = []
        self.body_to_group = {}

    # -------------------------------------------------- 入口
    def build(self):
        vrm = self.vrm
        self._build_colliders()
        if vrm.springs:
            self._build_springs(vrm.springs)
        elif self.options.get("auto_physics", True):
            chains = auto_generate_chains(self.doc, self.bones)
            if chains:
                self._build_springs(chains)
                self.warnings.append(
                    "该 VRM 没有 SpringBone 数据，已按骨骼名自动生成 %d 条物理链"
                    "（头发/裙摆等），可在 MMD 里自行调整。" % len(chains))
        if not self.rigidbodies:
            self.warnings.append("转换结果不含物理（刚体/关节），头发与裙摆不会摆动。")
        return self.rigidbodies, self.joints, self.warnings

    # -------------------------------------------------- 碰撞体
    def _build_colliders(self):
        vrm = self.vrm
        tf = self.transform
        counts = {}
        for i, col in enumerate(vrm.colliders):
            bone = self.bones.node_bone.get(col.node)
            if bone is None:
                bone = self.bones.bone_for_node(col.node)
            if bone is None:
                continue
            matrix = self.doc.world_matrix(col.node)
            if col.shape == "capsule":
                a_local = col.offset
                b_local = col.tail
                aw = _apply(matrix, a_local)
                bw = _apply(matrix, b_local)
                a = tf.point(aw)
                b = tf.point(bw)
                length = _dist(a, b)
                radius = tf.length(col.radius)
                if length > 1e-4:
                    direction = _sub(b, a)
                    body = P.PmxRigidBody()
                    body.shape_type = P.SHAPE_CAPSULE
                    body.shape_size = (radius, length, 0.0)
                    body.shape_position = _mid(a, b)
                    body.shape_rotation = euler_for_direction(direction)
                else:
                    body = P.PmxRigidBody()
                    body.shape_type = P.SHAPE_SPHERE
                    body.shape_size = (radius, 0.0, 0.0)
                    body.shape_position = a
                    body.shape_rotation = (0.0, 0.0, 0.0)
            else:
                offset_world = _apply(matrix, col.offset)
                center = tf.point(offset_world)
                body = P.PmxRigidBody()
                body.shape_type = P.SHAPE_SPHERE
                body.shape_size = (tf.length(col.radius), 0.0, 0.0)
                body.shape_position = center
                body.shape_rotation = (0.0, 0.0, 0.0)

            body.name = (self.bones.bones[bone].name or "collider") + "_col%d" % i
            body.english_name = body.name
            body.bone_index = bone
            body.mode = P.RIGIDBODY_FOLLOW_BONE
            body.collision_group = BODY_GROUP
            body.no_collision_group = 0xFFFF & ~(1 << BODY_GROUP)
            body.mass = 1.0
            body.linear_damping = 1.0
            body.angular_damping = 1.0
            body.restitution = 0.0
            body.friction = 0.5
            self.rigidbodies.append(body)
            counts[bone] = counts.get(bone, 0) + 1

    # -------------------------------------------------- 物理链
    def _build_springs(self, springs):
        tf = self.transform
        group = FIRST_CHAIN_GROUP
        built = 0
        for spring in springs:
            nodes = [j.node for j in spring.joints]
            bone_indices = []
            for node in nodes:
                bone = self.bones.node_bone.get(node)
                if bone is None:
                    bone = self.bones.bone_for_node(node)
                bone_indices.append(bone)
            bone_indices = [b for b in bone_indices if b is not None]
            if len(bone_indices) < 2:
                continue
            if len(bone_indices) > 64:
                bone_indices = bone_indices[:64]
            g = group
            group += 1
            if group > MAX_GROUP:
                group = FIRST_CHAIN_GROUP
            chain_bodies = []
            params = self._joint_params(spring, len(bone_indices))

            for k, bone in enumerate(bone_indices):
                pos = self.bones.bones[bone].position
                if k + 1 < len(bone_indices):
                    nxt = self.bones.bones[bone_indices[k + 1]].position
                    a, b = pos, nxt
                elif k > 0:
                    prev = self.bones.bones[bone_indices[k - 1]].position
                    a, b = prev, pos
                else:
                    a = b = pos
                radius, stiffness, drag = params[k]
                seg = _dist(a, b)
                radius = max(radius, min(0.15, seg * 0.2) if seg > 0 else 0.05)
                body = P.PmxRigidBody()
                body.name = (self.bones.bones[bone].name or "bone") + "_rb"
                body.english_name = body.name
                body.bone_index = bone
                body.mode = (P.RIGIDBODY_FOLLOW_BONE if k == 0
                             else P.RIGIDBODY_PHYSICS_BONE)
                body.collision_group = g
                body.no_collision_group = 0xFFFF & ~(1 << BODY_GROUP)
                body.mass = 1.0
                body.linear_damping = _clamp(0.4 + 0.6 * drag)
                body.angular_damping = _clamp(0.4 + 0.6 * drag)
                body.restitution = 0.0
                body.friction = 0.5
                if seg > 1e-4:
                    body.shape_type = P.SHAPE_CAPSULE
                    body.shape_size = (radius, seg, 0.0)
                    body.shape_position = _mid(a, b)
                    body.shape_rotation = euler_for_direction(_sub(b, a))
                else:
                    body.shape_type = P.SHAPE_SPHERE
                    body.shape_size = (radius, 0.0, 0.0)
                    body.shape_position = pos
                    body.shape_rotation = (0.0, 0.0, 0.0)
                self.rigidbodies.append(body)
                chain_bodies.append((body, stiffness, seg))

            # 关节：连接相邻刚体
            for k in range(len(chain_bodies) - 1):
                b0, stiff0, _s0 = chain_bodies[k]
                b1, stiff1, _s1 = chain_bodies[k + 1]
                joint = P.PmxJoint()
                joint.name = "%s_j" % b1.name
                joint.english_name = joint.name
                joint.joint_type = P.JOINT_SPRING6DOF
                joint.rigidbody_index_a = self.rigidbodies.index(b0)
                joint.rigidbody_index_b = self.rigidbodies.index(b1)
                joint.position = b1.shape_position
                joint.rotation = b1.shape_rotation
                joint.translation_limit_min = (0.0, 0.0, 0.0)
                joint.translation_limit_max = (0.0, 0.0, 0.0)
                bend = math.radians(30.0 + 60.0 * (1.0 - _clamp(stiff1)))
                twist = math.radians(20.0)
                joint.rotation_limit_min = (-bend, -twist, -bend)
                joint.rotation_limit_max = (bend, twist, bend)
                spring = 1.0 + 99.0 * _clamp(stiff1)
                joint.spring_constant_translation = (0.0, 0.0, 0.0)
                joint.spring_constant_rotation = (spring, spring, spring)
                self.joints.append(joint)
            built += 1
        if built == 0 and self.vrm.springs:
            self.warnings.append("VRM 的 SpringBone 数据里没有可用骨骼，未生成物理链。")

    def _joint_params(self, spring, count):
        """返回每个关节的 (半径, 刚度, 阻尼)。"""
        out = []
        for j in spring.joints[:count]:
            out.append((max(0.02, j.hit_radius), _clamp(j.stiffness), _clamp(j.drag_force)))
        while len(out) < count:
            out.append(out[-1] if out else (0.05, 0.5, 0.5))
        return out


def _apply(matrix, p):
    return (matrix[0] * p[0] + matrix[4] * p[1] + matrix[8] * p[2] + matrix[12],
            matrix[1] * p[0] + matrix[5] * p[1] + matrix[9] * p[2] + matrix[13],
            matrix[2] * p[0] + matrix[6] * p[1] + matrix[10] * p[2] + matrix[14])


def _clamp(v, lo=0.0, hi=1.0):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ------------------------------------------------------------------ 自动物理


def auto_generate_chains(doc, bones):
    """VRM 没有 SpringBone 时，按骨骼名把头发/裙摆等串成链。"""
    import math as _m

    def keyword_of(name):
        low = (name or "").lower()
        for tag, words in SPRING_KEYWORDS:
            for w in words:
                if w.lower() in low:
                    return tag
        return None

    # 收集骨骼节点与它们的关键词
    node_kind = {}
    for node, bone in bones.node_bone.items():
        kind = keyword_of(bones.bones[bone].name)
        if kind:
            node_kind[node] = kind
    if not node_kind:
        return []

    children = {}
    for node, bone in bones.node_bone.items():
        parent = doc.parent_of(node)
        children.setdefault(parent, []).append(node)

    def chain_children(node):
        return [c for c in children.get(node, []) if c in node_kind]

    # 链根 = 没有"同关键词祖先"的节点
    roots = []
    for node in sorted(node_kind):
        kind = node_kind[node]
        cur = doc.parent_of(node)
        same = False
        guard = 0
        while cur is not None and guard < 4096:
            if node_kind.get(cur) == kind:
                same = True
                break
            cur = doc.parent_of(cur)
            guard += 1
        if not same:
            roots.append(node)

    chains = []
    for root in roots:
        kind = node_kind[root]
        # 沿着唯一同关键词子节点往下走
        path = [root]
        cur = root
        guard = 0
        while guard < 64:
            kids = chain_children(cur)
            if len(kids) != 1:
                break
            cur = kids[0]
            path.append(cur)
            guard += 1
        if len(path) < 2:
            continue
        # 刚度/阻尼按类型给默认值
        if kind in ("skirt", "sleeve", "cape", "tie", "ribbon"):
            stiffness, drag, radius = 0.5, 0.5, 0.35
        elif kind in ("hair", "tail", "ahoge"):
            stiffness, drag, radius = 0.3, 0.4, 0.25
        else:
            stiffness, drag, radius = 0.4, 0.4, 0.3
        from .vrm import VrmSpring, VrmJoint
        spring = VrmSpring(kind, joints=[
            VrmJoint(node, hit_radius=radius, stiffness=stiffness, drag_force=drag,
                     gravity_power=1.0, gravity_dir=(0.0, -1.0, 0.0))
            for node in path])
        chains.append(spring)
    return chains
