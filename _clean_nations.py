"""清理国家归属数据：去掉 country_ 前缀，处理未匹配飞机。"""
import json
from pathlib import Path
from collections import Counter

# 读取原始国家映射
raw_map = json.loads(Path("data/_nations.json").read_text(encoding="utf-8"))

# 读取飞机列表
aircraft_list = Path("data/_all_aircraft.txt").read_text(encoding="utf-8").strip().split("\n")

# 去掉 country_ 前缀
clean_map = {}
for ac, nat in raw_map.items():
    if nat and nat.startswith("country_"):
        clean_map[ac] = nat.replace("country_", "")
    elif nat:
        clean_map[ac] = nat

# 处理未匹配的飞机：通过名称前缀启发式判断
NAME_PREFIX_MAP = {
    # USA
    "a-": "usa", "p-": "usa", "f-": "usa", "f4": "usa", "f8": "usa",
    "pb": "usa", "pbj": "usa", "pby": "usa", "pbm": "usa", "b-": "usa",
    "a2d": "usa", "a4": "usa", "a6": "usa", "a7": "usa", "ad": "usa",
    "ah-": "usa", "b-52": "usa", "b-57": "usa", "b-29": "usa", "b-25": "usa",
    "tbf": "usa", "tbd": "usa", "os2u": "usa", "sbd": "usa", "sb2c": "usa",
    "sb2u": "usa", "f6f": "usa", "f4f": "usa", "f8f": "usa", "f9f": "usa",
    "f7f": "usa", "f-80": "usa", "f-84": "usa", "f-86": "usa", "f-89": "usa",
    "f-100": "usa", "f-104": "usa", "f-105": "usa", "f-106": "usa", "f-111": "usa",
    "f-4": "usa", "f-5": "usa", "f-14": "usa", "f-15": "usa", "f-16": "usa",
    "a-10": "usa", "a-20": "usa", "a-26": "usa", "a-1": "usa", "a-6": "usa",
    "a-7": "usa", "uh": "usa", "oh": "usa", "yah": "usa", "xa": "usa",
    "xf": "usa", "xp": "usa", "p-59": "usa", "p-61": "usa", "p-63": "usa",
    "p-39": "usa", "p-40": "usa", "p-47": "usa", "p-51": "usa", "p-36": "usa",
    "p-38": "usa", "p-26": "usa", "p-43": "usa", "p-66": "usa", "p-75": "usa",
    "np": "usa", "pv": "usa", "jbp": "usa", "bj": "usa", "boston": "usa",
    "shark": "usa", "wyvern": "britain",
    # USSR
    "su-": "ussr", "su_": "ussr", "mig": "ussr", "mig-": "ussr",
    "yak-": "ussr", "yak_": "ussr", "la-": "ussr", "la_": "ussr",
    "il-": "ussr", "il_": "ussr", "pe-": "ussr", "tu-": "ussr", "tu_": "ussr",
    "po-": "ussr", "po_": "ussr", "tb-": "ussr", "sb_": "ussr",
    "i-": "ussr", "i_": "ussr", "bb-": "ussr", "ar-": "ussr",
    "mi-": "ussr", "ka-": "ussr", "v_": "ussr", "tis": "ussr",
    "sh": "ussr", "er": "ussr", "nt_": "ussr", "tu_14": "ussr",
    "su_1": "ussr", "lg": "ussr", "lagg": "ussr", "yak": "ussr",
    # Germany
    "bf": "germany", "bf-": "germany", "bf1": "germany", "bf1_": "germany",
    "fw": "germany", "fw-": "germany", "fw_": "germany", "ta-": "germany",
    "ta_": "germany", "me": "germany", "me-": "germany", "he_": "germany",
    "he-": "germany", "do_": "germany", "do-": "germany", "ju_": "germany",
    "ju-": "germany", "hs_": "germany", "hs-": "germany", "ar_": "germany",
    "ar-": "germany", "bv_": "germany", "bv-": "germany", "go_": "germany",
    "go-": "germany", "fi_": "germany", "fi-": "germany", "ho_": "germany",
    "ho-": "germany", "me_": "germany", "hsc": "germany",
    # Britain
    "spitfire": "britain", "hurri": "britain", "tempest": "britain",
    "typhoon": "britain", "mosquito": "britain", "beaufighter": "britain",
    "wellington": "britain", "lancaster": "britain", "stirling": "britain",
    "halifax": "britain", "firefly": "britain", "firebrand": "britain",
    "fulmar": "britain", "swordfish": "britain", "walrus": "britain",
    "sea_": "britain", "vampire": "britain", "venom": "britain",
    "swift": "britain", "hunter": "britain", "meteor": "britain",
    "attacker": "britain", "scimitar": "britain", "scimitar_": "britain",
    "lightning": "britain", "harrier": "britain", "tornado": "britain",
    "buccaneer": "britain", "jaguar": "britain", "phantom": "britain",
    "lynx": "britain", "gazelle": "britain", "wessex": "britain",
    "wasp": "britain", "whirlwind": "britain", "albacore": "britain",
    "barracuda": "britain", "skua": "britain", "rocs": "britain",
    "defiant": "britain", "gladiator": "britain", "gauntlet": "britain",
    "fairy": "britain", "fairey": "britain", "battle": "britain",
    "blenheim": "britain", "beaufort": "britain", "hampden": "britain",
    "whitley": "britain", "airspeed": "britain", "welkin": "britain",
    "wind": "britain", "hornet": "britain", "nighthunter": "britain",
    "tornado_f": "britain", "tornado_gr": "britain", "tornado_adv": "britain",
    "tornado_ids": "britain",
    # Japan
    "a6m": "japan", "a5m": "japan", "a7m": "japan", "a7he": "japan",
    "j2m": "japan", "j7w": "japan", "n1k": "japan", "ki-": "japan",
    "ki_": "japan", "b7a": "japan", "b5n": "japan", "b6n": "japan",
    "d3a": "japan", "d4y": "japan", "g4m": "japan", "g5n": "japan",
    "g8n": "japan", "p1y": "japan", "h8k": "japan", "h6k": "japan",
    "f1m": "japan", "e13a": "japan", "e16a": "japan", "r2y": "japan",
    "s6m": "japan", "tandem": "japan", "shiden": "japan", "raiden": "japan",
    "zero": "japan", "reisen": "japan", "george": "japan", "jack": "japan",
    "frances": "japan", "betty": "japan", "sally": "japan", "peggy": "japan",
    "lily": "japan", "ann": "japan", "val": "japan", "kate": "japan",
    "dave": "japan", "pete": "japan", "jake": "japan", "emily": "japan",
    "mavis": "japan", "nancy": "japan", "rex": "japan", "myrt": "japan",
    "jill": "japan", "judy": "japan", "grace": "japan", "ginga": "japan",
    "renzan": "japan", "shinzan": "japan", "tanzan": "japan", "saiun": "japan",
    "suisei": "japan", "tenzan": "japan", "ryusei": "japan", "reppu": "japan",
    "shiden_kai": "japan",
    # France
    "d_5": "france", "d_3": "france", "d_510": "france", "d_520": "france",
    "mb_": "france", "mb1": "france", "mb2": "france", "leO": "france",
    "leo_": "france", "amiot": "france", "potez": "france", "breguet": "france",
    "brewster": "france", "osprey": "france", "v_156": "france",
    "p-36a_rasmussen": "france", "p-36a": "france", "spad": "france",
    "nio": "france", "nc_": "france", "vb_": "france", "vg_": "france",
    "armac": "france", "mirage": "france", "etendard": "france",
    "super_etendard": "france", "jaguar_": "france", "mystere": "france",
    "ouragan": "france", "vautour": "france", "nord": "france",
    "trident": "france", "leduc": "france", "gerfaut": "france",
    "baroudeur": "france", "griffon": "france", "durandal": "france",
    "sea_venom": "france", "aquilon": "france", "sud_": "france",
    "a_35b": "sweden",
    # Italy
    "re_2": "italy", "re_2": "italy", "mc_": "italy", "mc2": "italy",
    "g_5": "italy", "g_5": "italy", "g_50": "italy", "g_55": "italy",
    "fiat_": "italy", "fiat": "italy", "sai_": "italy", "imam": "italy",
    "ro_": "italy", "can": "italy", "sm_": "italy", "br_": "italy",
    "z_1": "italy", "ba_": "italy", "a_129": "italy", "tornado_ids_it": "italy",
    "amx": "italy", "sagittario": "italy", "aerfer": "italy",
    "pyorremyrsky": "italy",
    # China
    "j_": "china", "jf_": "china", "q_": "china", "h_": "china",
    "a5m4_china": "china", "p-40c_china": "china", "p-51": "china",
    "spitfire_ix_cw": "china", "do_335": "germany",
    # Sweden
    "saab_": "sweden", "saab": "sweden", "a21": "sweden", "j21": "sweden",
    "j29": "sweden", "j32": "sweden", "j35": "sweden", "ja37": "sweden",
    "jas39": "sweden", "b17": "sweden", "b18": "sweden", "t18": "sweden",
    "j22": "sweden", "a32": "sweden", "sk60": "sweden",
    "vl_": "sweden", "pyorre": "sweden", "xffw_190": "germany",
    # Israel
    "nesh": "israel", "kfir": "israel", "lavi": "israel",
    "mirage_5": "israel", "nasher": "israel", "kef": "israel",
    "t_kfir": "israel", "ah_64": "usa",
    # 补充规则
    "am-": "usa", "arado": "germany", "av_": "britain", "c-47": "usa",
    "db_": "ussr", "dh_": "britain", "dummy": "other", "f13": "germany",
    "f_100": "usa", "f_104g": "germany", "f_104j": "japan", "f_104s": "italy",
    "f_104a": "usa", "f_104c": "usa", "f_105": "usa", "f_111": "usa",
    "f_16a": "usa", "f_2000a": "italy", "f_5": "usa", "fau": "britain",
    "hp52": "britain", "iar": "italy", "itp": "ussr", "li-": "ussr",
    "li_": "ussr", "maryland": "britain", "ms_": "france",
    "night_fighter": "britain", "p_43": "usa", "p_51b_7_sweden": "sweden",
    "p_59": "usa", "pandora": "britain", "uav": "other", "f_104s_asa": "italy",
    "f_104s_cb": "italy", "f_5e_aidc": "china", "f_5e_fcu": "france",
    "f_5t_": "china", "f_5th_": "china", "f_5c_turkey": "china",
    "f_5ag": "china", "f_5e": "usa", "f_16a_block": "usa",
}

not_found = [ac for ac in aircraft_list if ac not in clean_map]
print(f"清理后匹配: {len(clean_map)} / {len(aircraft_list)}")
print(f"未匹配: {len(not_found)}")

# 启发式匹配
heuristic_matched = 0
still_unmatched = []
for ac in not_found:
    matched = False
    ac_lower = ac.lower()
    for prefix, nation in NAME_PREFIX_MAP.items():
        if ac_lower.startswith(prefix):
            clean_map[ac] = nation
            matched = True
            heuristic_matched += 1
            break
    if not matched:
        still_unmatched.append(ac)

print(f"启发式匹配: {heuristic_matched}")
print(f"仍未匹配: {len(still_unmatched)}")
if still_unmatched:
    print(f"未匹配列表: {still_unmatched}")

# 将未匹配的归为"其他"
for ac in still_unmatched:
    clean_map[ac] = "other"

# 统计
NATION_CN = {
    "usa": "美", "ussr": "苏", "germany": "德", "china": "中",
    "france": "法", "italy": "意", "britain": "英", "japan": "日",
    "israel": "以", "sweden": "瑞", "other": "其他",
}
dist = Counter(clean_map.values())
print(f"\n最终国家分布:")
for nat, count in dist.most_common():
    cn = NATION_CN.get(nat, nat)
    print(f"  {cn}({nat}): {count} 架")
print(f"  总计: {sum(dist.values())} 架")

# 保存
Path("data/_nations.json").write_text(
    json.dumps(clean_map, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n已保存 data/_nations.json ({len(clean_map)} 条)")
