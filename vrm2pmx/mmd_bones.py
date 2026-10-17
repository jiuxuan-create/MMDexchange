# -*- coding: utf-8 -*-
"""把 VRM 人形骨骼映射成 MMD 標準ボーン，并补齐 MMD 需要的控制骨与 IK。

设计要点（全部依据对真实 PMX 模型的反推，见 tools/ref_report.txt）：
  * VRM hips -> センター，spine -> 上半身，chest -> 上半身2，upperChest -> 上半身3
  * 插入 MMD 专有的 グルーブ / 腰 / 下半身，使 上半身 与 下半身 同级挂在 腰 下
  * 腿：下半身 -> 左足 -> 左ひざ -> 左足首 -> 左つま先
  * 眼睛：両目（頭 上方 3 MMD 单位）+ 左目/右目（回転付与 -> 両目，付与率 1.0）
  * 腿部 IK：左足ＩＫ（位于足首、loop=40、ひざ 限制 -162.5°~-0.5°）
            左つま先ＩＫ（位于つま先、loop=3、父为足ＩＫ）
  * 所有骨骼位置都直接用「世界坐标 -> 目标坐标」算出；
    PMX 骨骼位置本就是模型空间绝对坐标，因此重整父子关系不会破坏静止姿势
"""

import math

from . import pmx_model as P

__all__ = ["BoneSet", "HUMANOID_TO_MMD", "build_bones", "MMD_FINGER_NAMES",
           "panel_of_morph_name", "EYES_CONTROL_OFFSET"]

FLAG_TAIL = P.BONEFLAG_TAIL_IS_BONE
FLAG_ROT = P.BONEFLAG_CAN_ROTATE
FLAG_MOV = P.BONEFLAG_CAN_TRANSLATE
FLAG_VIS = P.BONEFLAG_IS_VISIBLE
FLAG_MAN = P.BONEFLAG_CAN_MANIPULATE
FLAG_IK = P.BONEFLAG_IS_IK
FLAG_APPEND = P.BONEFLAG_IS_EXTERNAL_ROTATION

BASE = FLAG_ROT | FLAG_VIS | FLAG_MAN            # 0x001a，普通骨
MOVABLE = BASE | FLAG_MOV                        # 0x001e，可移动骨

# 両目 控制骨摆在 頭 上方 3 个 MMD 单位处（与参考模型一致）
EYES_CONTROL_OFFSET = 3.0

FW = {"0": "\uff10", "1": "\uff11", "2": "\uff12", "3": "\uff13"}
THUMB0, THUMB1, THUMB2 = "\uff10", "\uff11", "\uff12"

# VRM 骨骼 -> MMD 骨骼名
HUMANOID_TO_MMD = {
    "spine": "\u4e0a\u534a\u8eab",
    "chest": "\u4e0a\u534a\u8eab2",
    "upperChest": "\u4e0a\u534a\u8eab3",
    "neck": "\u9996",
    "head": "\u982d",
    "leftEye": "\u5de6\u76ee",
    "rightEye": "\u53f3\u76ee",
    "leftShoulder": "\u5de6\u80a9",
    "leftUpperArm": "\u5de6\u8155",
    "leftLowerArm": "\u5de6\u3072\u3058",
    "leftHand": "\u5de6\u624b\u9996",
    "rightShoulder": "\u53f3\u80a9",
    "rightUpperArm": "\u53f3\u8155",
    "rightLowerArm": "\u53f3\u3072\u3058",
    "rightHand": "\u53f3\u624b\u9996",
    "leftUpperLeg": "\u5de6\u8db3",
    "leftLowerLeg": "\u5de6\u3072\u3056",
    "leftFoot": "\u5de6\u8db3\u9996",
    "leftToes": "\u5de6\u3064\u307e\u5148",
    "rightUpperLeg": "\u53f3\u8db3",
    "rightLowerLeg": "\u53f3\u3072\u3056",
    "rightFoot": "\u53f3\u8db3\u9996",
    "rightToes": "\u53f3\u3064\u307e\u5148",
}

FINGER_MAP = {}
_stage_pairs = (("ThumbMetacarpal", THUMB0), ("ThumbProximal", THUMB1),
                ("ThumbDistal", THUMB2))
for _side in ("left", "right"):
    for _k, _n in _stage_pairs:
        FINGER_MAP[_side + _k] = _n
    for _j, _nums in (("Index", ("\uff11", "\uff12", "\uff13")),
                      ("Middle", ("\uff11", "\uff12", "\uff13")),
                      ("Ring", ("\uff11", "\uff12", "\uff13")),
                      ("Little", ("\uff11", "\uff12", "\uff13"))):
        for _st, _n in zip(("Proximal", "Intermediate", "Distal"), _nums):
            FINGER_MAP[_side + _j + _st] = _n

_JP_FINGER = {"Index": "\u4eba\u6307", "Middle": "\u4e2d\u6307",
              "Ring": "\u85ac\u6307", "Little": "\u5c0f\u6307"}


def _finger_mmd_name(vrm_name):
    """leftIndexProximal -> 左人指１"""
    side = "\u5de6" if vrm_name.startswith("left") else "\u53f3"
    rest = vrm_name[4:] if vrm_name.startswith("left") else vrm_name[5:]
    if rest.startswith("Thumb"):
        return side + "\u89aa\u6307" + FINGER_MAP[vrm_name]
    for en, jp in _JP_FINGER.items():
        if rest.startswith(en):
            return side + jp + FINGER_MAP[vrm_name]
    return side + rest


for _k in FINGER_MAP:
    HUMANOID_TO_MMD[_k] = _finger_mmd_name(_k)

MMD_FINGER_NAMES = dict(HUMANOID_TO_MMD)

_EN_FINGER = {"Index": "Index", "Middle": "Middle", "Ring": "Ring", "Little": "Little"}

ENGLISH_NAMES = {
    "\u5168\u3066\u306e\u89aa": "root",
    "\u30bb\u30f3\u30bf\u30fc": "center",
    "\u30b0\u30eb\u30fc\u30d6": "groove",
    "\u8170": "waist",
    "\u4e0a\u534a\u8eab": "upper body",
    "\u4e0a\u534a\u8eab2": "upper body2",
    "\u4e0a\u534a\u8eab3": "upper body3",
    "\u4e0b\u534a\u8eab": "lower body",
    "\u9996": "neck",
    "\u982d": "head",
    "\u4e21\u76ee": "eyes",
    "\u5de6\u76ee": "left eye",
    "\u53f3\u76ee": "right eye",
    "\u5de6\u80a9": "left shoulder",
    "\u5de6\u8155": "left arm",
    "\u5de6\u3072\u3058": "left elbow",
    "\u5de6\u624b\u9996": "left wrist",
    "\u53f3\u80a9": "right shoulder",
    "\u53f3\u8155": "right arm",
    "\u53f3\u3072\u3058": "right elbow",
    "\u53f3\u624b\u9996": "right wrist",
    "\u5de6\u8db3": "left leg",
    "\u5de6\u3072\u3056": "left knee",
    "\u5de6\u8db3\u9996": "left ankle",
    "\u5de6\u3064\u307e\u5148": "left toe",
    "\u53f3\u8db3": "right leg",
    "\u53f3\u3072\u3056": "right knee",
    "\u53f3\u8db3\u9996": "right ankle",
    "\u53f3\u3064\u307e\u5148": "right toe",
    "\u5de6\u8db3\uff29\uff2b": "left leg IK",
    "\u53f3\u8db3\uff29\uff2b": "right leg IK",
    "\u5de6\u3064\u307e\u5148\uff29\uff2b": "left toe IK",
    "\u53f3\u3064\u307e\u5148\uff29\uff2b": "right toe IK",
    "\u5de6\u8db3IK\u89aa": "left leg IK parent",
    "\u53f3\u8db3IK\u89aa": "right leg IK parent",
}
for _side in ("left", "right"):
    for _jp, _en in _JP_FINGER.items():
        ENGLISH_NAMES[("\u5de6" if _side == "left" else "\u53f3") + _en] = ""
    for _n in ("\uff10", "\uff11", "\uff12"):
        ENGLISH_NAMES[("\u5de6" if _side == "left" else "\u53f3") + "\u89aa\u6307" + _n] = ""
for _vrm, _mmd in HUMANOID_TO_MMD.items():
    if _vrm.startswith("left") or _vrm.startswith("right"):
        side_en = "left" if _vrm.startswith("left") else "right"
        rest = _vrm[len(side_en):]
        for en in ("ThumbMetacarpal", "ThumbProximal", "ThumbDistal"):
            if rest.startswith(en):
                ENGLISH_NAMES[_mmd] = side_en + en.replace("ThumbMetacarpal", "Thumb0")\
                    .replace("ThumbProximal", "Thumb1").replace("ThumbDistal", "Thumb2")
        for en in ("Index", "Middle", "Ring", "Little"):
            for i, st in enumerate(("Proximal", "Intermediate", "Distal")):
                if rest == en + st:
                    ENGLISH_NAMES[_mmd] = "%s%s%d" % (side_en, en, i + 1)

# MMD 表情面板：0=システム 1=眉 2=目 3=口 4=その他
PANEL_BY_NAME = {}
for _n in ("\u771f\u9762\u76ee", "\u56f0\u308b", "\u6012\u308a", "\u306b\u3053\u308a",
           "\u4e0a", "\u4e0b", "\u524d"):
    PANEL_BY_NAME[_n] = 1
for _n in ("\u307e\u3070\u305f\u304d", "\u7b11\u3044", "\u30a6\u30a3\u30f3\u30af",
           "\u30a6\u30a3\u30f3\u30af\u53f3", "\u3073\u3063\u304f\u308a",
           "\u3058\u3068\u76ee", "\u6012\u308a\u76ee", "\u6012\u308a\u76ee\uff12",
           "\u60b2\u3057\u3080", "\u773c\u89d2\u4e0b", "\u4e0b\u773c\u4e0a", "\u306f\u3045"):
    PANEL_BY_NAME[_n] = 2
for _n in ("\u3042", "\u3044", "\u3046", "\u3048", "\u304a", "\u3048\uff12",
           "\u30ef", "\u30ef\uff12", "M", "\u306b\u3084\u308a", "\u306b\u3084\u308a\uff12",
           "\u53e3\u89d2\u4e0a\u3052", "\u53e3\u6a2a\u5e83\u3052", "\u53e3\u6a2a\u72ed\u3081",
           "\u53e3\u89d2\u4e0b\u3052", "\u53e3\u4e0a", "\u53e3\u4e0b", "\u53e3\u5de6",
           "\u53e3\u53f3", "\u6b6f\u4e0a", "\u6b6f\u4e0b"):
    PANEL_BY_NAME[_n] = 3


def panel_of_morph_name(name):
    """按 MMD 惯用名推断表情面板编号，未知则放「その他」(4)。"""
    return PANEL_BY_NAME.get(name, 4)


def is_default_panel(name):
    return name in PANEL_BY_NAME


class BoneSet(object):
    """收集并构建 PMX 骨骼。"""

    def __init__(self, transform):
        self.transform = transform
        self.doc = transform.doc
        self.bones = []
        self.node_bone = {}
        self.by_name = {}
        self.warnings = []

    def bone_for_node(self, node):
        """找节点自身或最近的祖先骨骼；找不到就退回 全ての親。"""
        if node is None:
            return self.index("\u5168\u3066\u306e\u89aa")
        cur = node
        guard = 0
        while cur is not None and guard < 8192:
            if cur in self.node_bone:
                return self.node_bone[cur]
            cur = self.doc.parent_of(cur)
            guard += 1
        return self.index("\u5168\u3066\u306e\u89aa")

    # -------------------------------------------------- 基础
    def add(self, name, position, parent=-1, flags=None, tail_index=-1,
            tail_position=None, append_parent=-1, append_ratio=0.0,
            ik=None, english="", layer=0):
        idx = len(self.bones)
        bone = P.PmxBone()
        bone.name = name
        bone.english_name = english or ENGLISH_NAMES.get(name, "")
        bone.position = tuple(float(v) for v in position)
        bone.parent_index = parent
        bone.layer = layer
        if flags is None:
            flags = BASE
        if tail_index >= 0:
            flags |= FLAG_TAIL
            bone.tail_index = tail_index
            bone.tail_position = (0.0, 0.0, 0.0)
        else:
            flags &= ~FLAG_TAIL
            bone.tail_index = -1
            bone.tail_position = tuple(float(v) for v in (
                tail_position if tail_position is not None else (0.0, 0.6, 0.0)))
        if append_parent >= 0:
            flags |= FLAG_APPEND
            bone.effect_index = append_parent
            bone.effect_factor = float(append_ratio)
        if ik is not None:
            flags |= FLAG_IK
            bone.ik = ik
        bone.flag = flags
        self.bones.append(bone)
        if name not in self.by_name:
            self.by_name[name] = idx
        return idx

    def index(self, name):
        return self.by_name.get(name, -1)

    def unique_name(self, name):
        if name not in self.by_name:
            return name
        i = 2
        while "%s_%d" % (name, i) in self.by_name:
            i += 1
        return "%s_%d" % (name, i)

    def pos_of(self, idx):
        return self.bones[idx].position

    # -------------------------------------------------- 构建
    def build(self, vrm):
        doc = self.transform.doc
        hum = vrm.humanoid_bones
        tf = self.transform

        def wpos(vrm_bone):
            node = hum.get(vrm_bone)
            if node is None:
                return None
            return tf.point(doc.world_translation(node))

        def has(vrm_bone):
            return vrm_bone in hum

        # ---- 1. 根与身体主轴 ----
        root = self.add("\u5168\u3066\u306e\u89aa", (0.0, 0.0, 0.0), -1,
                        flags=MOVABLE, tail_position=(0.0, 0.6, 0.0))
        hips_pos = wpos("hips")
        if hips_pos is None:
            hips_pos = (0.0, 0.0, 0.0)
            self.warnings.append("VRM 缺少 hips，センター 放在原点，模型可能错位。")
        center = self.add("\u30bb\u30f3\u30bf\u30fc", hips_pos, root, flags=MOVABLE,
                          tail_position=(0.0, hips_pos[1] + 0.6, 0.0))
        groove = self.add("\u30b0\u30eb\u30fc\u30d6", hips_pos, center, flags=MOVABLE,
                          tail_position=(0.0, hips_pos[1] + 0.6, 0.0))
        waist = self.add("\u8170", hips_pos, groove, flags=MOVABLE,
                         tail_position=(0.0, hips_pos[1] + 0.6, 0.0))
        lower_body = self.add("\u4e0b\u534a\u8eab", hips_pos, waist,
                              tail_position=(0.0, hips_pos[1] + 0.6, 0.0))

        upper_body = -1
        if has("spine"):
            upper_body = self.add(HUMANOID_TO_MMD["spine"], wpos("spine"), waist,
                                  tail_position=wpos("chest") or wpos("neck")
                                  or wpos("head") or (0.0, 0.0, 0.0))
            self.node_bone[hum["spine"]] = upper_body
        elif has("chest") or has("upperChest") or has("neck"):
            upper_body = self.add(HUMANOID_TO_MMD["spine"],
                                  (hips_pos[0], hips_pos[1] + 0.6, hips_pos[2]), waist,
                                  tail_position=(hips_pos[0], hips_pos[1] + 1.2,
                                                 hips_pos[2]))
            self.warnings.append(
                "VRM 缺少 spine，上半身 为占位骨（不参与蒙皮，由子骨承担全部变形）。")
        parent_of_spine = upper_body if upper_body >= 0 else waist

        if has("chest"):
            idx = self.add(HUMANOID_TO_MMD["chest"], wpos("chest"), parent_of_spine,
                           tail_position=wpos("upperChest") or wpos("neck")
                           or wpos("head") or (0.0, 0.0, 0.0))
            self.node_bone[hum["chest"]] = idx
            parent_of_spine = idx
        if has("upperChest"):
            idx = self.add(HUMANOID_TO_MMD["upperChest"], wpos("upperChest"),
                           parent_of_spine,
                           tail_position=wpos("neck") or wpos("head") or (0.0, 0.0, 0.0))
            self.node_bone[hum["upperChest"]] = idx
            parent_of_spine = idx

        head = -1
        if has("neck"):
            neck = self.add(HUMANOID_TO_MMD["neck"], wpos("neck"), parent_of_spine,
                            tail_position=wpos("head") or (0.0, 0.0, 0.0))
            self.node_bone[hum["neck"]] = neck
            parent_of_head = neck
        else:
            parent_of_head = parent_of_spine
        if has("head"):
            head = self.add(HUMANOID_TO_MMD["head"], wpos("head"), parent_of_head,
                            tail_position=(0.0, 0.6, 0.0))
            self.node_bone[hum["head"]] = head
            hp = self.bones[head].position
            self.bones[head].tail_position = (hp[0], hp[1] + 0.6, hp[2])

        # ---- 2. 両目 / 左目 / 右目 ----
        if head >= 0:
            hp = self.bones[head].position
            eyes = self.add("\u4e21\u76ee",
                            (hp[0], hp[1] + EYES_CONTROL_OFFSET, hp[2]), head,
                            tail_position=(hp[0], hp[1] + EYES_CONTROL_OFFSET + 0.6, hp[2]))
            for vrm_name, mmd_name in (("leftEye", "\u5de6\u76ee"),
                                       ("rightEye", "\u53f3\u76ee")):
                if has(vrm_name):
                    idx = self.add(mmd_name, wpos(vrm_name), head,
                                   tail_position=(0.0, 0.4, 0.0),
                                   append_parent=eyes, append_ratio=1.0)
                    self.node_bone[hum[vrm_name]] = idx
        else:
            eyes = -1

        # ---- 3. 手臂与手指 ----
        for side, S in (("left", "\u5de6"), ("right", "\u53f3")):
            shoulder = -1
            if has(side + "Shoulder"):
                shoulder = self.add(S + "\u80a9", wpos(side + "Shoulder"),
                                    parent_of_spine,
                                    tail_position=wpos(side + "UpperArm") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "Shoulder"]] = shoulder
            arm_parent = shoulder if shoulder >= 0 else parent_of_spine
            arm = -1
            if has(side + "UpperArm"):
                arm = self.add(S + "\u8155", wpos(side + "UpperArm"), arm_parent,
                               tail_position=wpos(side + "LowerArm") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "UpperArm"]] = arm
            elbow = -1
            if has(side + "LowerArm"):
                elbow = self.add(S + "\u3072\u3058", wpos(side + "LowerArm"),
                                 arm if arm >= 0 else arm_parent,
                                 tail_position=wpos(side + "Hand") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "LowerArm"]] = elbow
            wrist = -1
            if has(side + "Hand"):
                wrist = self.add(S + "\u624b\u9996", wpos(side + "Hand"),
                                 elbow if elbow >= 0 else
                                 (arm if arm >= 0 else arm_parent),
                                 tail_position=(0.0, 0.0, 0.0))
                self.node_bone[hum[side + "Hand"]] = wrist
            if wrist >= 0:
                self._build_fingers(side, wrist, hum, wpos)

        # ---- 4. 腿 ----
        leg_root = {}
        for side, S in (("left", "\u5de6"), ("right", "\u53f3")):
            up = lo = ft = to = -1
            if has(side + "UpperLeg"):
                up = self.add(S + "\u8db3", wpos(side + "UpperLeg"), lower_body,
                              tail_position=wpos(side + "LowerLeg") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "UpperLeg"]] = up
            if has(side + "LowerLeg"):
                lo = self.add(S + "\u3072\u3056", wpos(side + "LowerLeg"),
                              up if up >= 0 else lower_body,
                              tail_position=wpos(side + "Foot") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "LowerLeg"]] = lo
            if has(side + "Foot"):
                ft = self.add(S + "\u8db3\u9996", wpos(side + "Foot"),
                              lo if lo >= 0 else (up if up >= 0 else lower_body),
                              tail_position=wpos(side + "Toes") or (0.0, 0.0, 0.0))
                self.node_bone[hum[side + "Foot"]] = ft
            if has(side + "Toes"):
                to = self.add(S + "\u3064\u307e\u5148", wpos(side + "Toes"),
                              ft if ft >= 0 else (lo if lo >= 0 else lower_body),
                              tail_position=(0.0, 0.0, 0.0))
                self.node_bone[hum[side + "Toes"]] = to
            leg_root[side] = (up, lo, ft, to)

        # ---- 5. 腿部 IK ----
        for side, S in (("left", "\u5de6"), ("right", "\u53f3")):
            up, lo, ft, to = leg_root[side]
            if lo < 0 or ft < 0:
                continue
            foot_pos = self.pos_of(ft)
            toe_pos = self.pos_of(to) if to >= 0 else (
                foot_pos[0], foot_pos[1] - 0.5, foot_pos[2] - 0.5)
            ground_y = min(toe_pos[1], foot_pos[1])
            ik_parent = self.add(S + "\u8db3IK\u89aa",
                                 (foot_pos[0], ground_y, foot_pos[2]), root,
                                 flags=MOVABLE,
                                 tail_position=(foot_pos[0], ground_y + 0.5, foot_pos[2]))
            ik = P.PmxIk()
            ik.target_index = ft
            ik.loop = 40
            ik.limit_radian = 2.0
            knee = P.PmxIkLink(lo, 1, (math.radians(-162.5), 0.0, 0.0),
                               (math.radians(-0.5), 0.0, 0.0))
            leg = P.PmxIkLink(up, 0)
            ik.links = [knee, leg]
            leg_ik = self.add(S + "\u8db3\uff29\uff2b", foot_pos, ik_parent,
                              flags=MOVABLE,
                              tail_position=(foot_pos[0], foot_pos[1] + 0.5, foot_pos[2]),
                              ik=ik)
            if to >= 0:
                tik = P.PmxIk()
                tik.target_index = to
                tik.loop = 3
                tik.limit_radian = 4.0
                tik.links = [P.PmxIkLink(ft, 0)]
                self.add(S + "\u3064\u307e\u5148\uff29\uff2b", toe_pos, leg_ik,
                         flags=MOVABLE,
                         tail_position=(toe_pos[0], toe_pos[1] + 0.4, toe_pos[2] - 0.4),
                         ik=tik)

        # ---- 6. 其余蒙皮关节 ----
        self._build_extra_joints(vrm, doc)

        # ---- 7. 收尾 ----
        self._resolve_tails()
        return self

    # -------------------------------------------------- 手指
    def _build_fingers(self, side, wrist, hum, wpos):
        order = ["Metacarpal", "Proximal", "Intermediate", "Distal"]
        prev_num = {"\uff10": None, "\uff11": "\uff10",
                    "\uff12": "\uff11", "\uff13": "\uff12"}
        for stage in order:
            for vrm_name in sorted(FINGER_MAP):
                if not vrm_name.startswith(side) or not vrm_name.endswith(stage):
                    continue
                if vrm_name not in hum:
                    continue
                mmd_name = HUMANOID_TO_MMD[vrm_name]
                if mmd_name in self.by_name:
                    continue
                num = FINGER_MAP[vrm_name]
                parent = wrist
                pn = prev_num.get(num)
                if pn:
                    cand = mmd_name[:mmd_name.index(num)] + pn
                    if cand in self.by_name:
                        parent = self.by_name[cand]
                idx = self.add(self.unique_name(mmd_name), wpos(vrm_name), parent,
                               tail_position=(0.0, 0.2, 0.0))
                self.node_bone[hum[vrm_name]] = idx

    # -------------------------------------------------- 其余关节
    def _build_extra_joints(self, vrm, doc):
        joints = set()
        for skin in (doc.json.get("skins") or []):
            for j in skin.get("joints") or []:
                if isinstance(j, int):
                    joints.add(j)
        # 没蒙皮的网格节点也建骨，让静态挂件能跟着模型走
        for i, node in enumerate(doc.nodes):
            if "mesh" in node and "skin" not in node:
                joints.add(i)
        hum_nodes = set(vrm.humanoid_bones.values())
        extra = sorted(n for n in joints if n not in hum_nodes)
        if not extra:
            return
        tf = self.transform

        def find_ancestor_bone(node):
            cur = doc.parent_of(node)
            guard = 0
            while cur is not None and guard < 8192:
                if cur in self.node_bone:
                    return self.node_bone[cur]
                cur = doc.parent_of(cur)
                guard += 1
            return self.index("\u5168\u3066\u306e\u89aa")

        def depth(node):
            d = 0
            cur = doc.parent_of(node)
            guard = 0
            while cur is not None and guard < 8192:
                d += 1
                cur = doc.parent_of(cur)
                guard += 1
            return d

        for node in sorted(extra, key=lambda n: (depth(n), n)):
            if node in self.node_bone:
                continue
            name = self.unique_name(_sanitize_bone_name(doc.node_name(node), node))
            if name == "\u5168\u3066\u306e\u89aa":
                name = "bone_%d" % node
            idx = self.add(name, tf.point(doc.world_translation(node)),
                           find_ancestor_bone(node), tail_position=(0.0, 0.3, 0.0))
            self.node_bone[node] = idx

    # -------------------------------------------------- 尾巴
    def _resolve_tails(self):
        children = {}
        for i, b in enumerate(self.bones):
            if b.parent_index >= 0:
                children.setdefault(b.parent_index, []).append(i)
        for i, b in enumerate(self.bones):
            if (b.flag & FLAG_TAIL) and b.tail_index >= 0:
                continue
            kids = children.get(i, [])
            if not kids:
                continue
            pos = b.position

            def score(c):
                p = self.bones[c].position
                # 优先选"向下延伸"的子骨，其次选位置最接近的
                dy = p[1] - pos[1]
                d = math.sqrt(sum((p[k] - pos[k]) ** 2 for k in range(3)))
                if d < 1e-6:
                    return (9e9, 9e9)
                return (0 if dy <= 0 else 1, d)

            best = min(kids, key=score)
            b.flag |= FLAG_TAIL
            b.tail_index = best
            b.tail_position = (0.0, 0.0, 0.0)


def _sanitize_bone_name(name, node):
    name = (name or "").strip()
    out = []
    for ch in name:
        out.append("_" if ch in "\\/:*?\"<>|" else ch)
    name = "".join(out)[:40].strip()
    return name or ("bone_%d" % node)


def build_bones(vrm, transform):
    bs = BoneSet(transform)
    bs.build(vrm)
    for w in bs.warnings:
        vrm.warnings.append(w)
    return bs
