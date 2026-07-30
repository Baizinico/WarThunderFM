import json

for aircraft in ['j_10c', 'su_27']:
    fm = json.load(open(f'data/raw/{aircraft}.blkx', 'r', encoding='utf-8'))
    print(f"=== {aircraft} 引擎结构 ===")
    for key in sorted(fm.keys()):
        if 'Engine' in key:
            eng = fm[key]
            if isinstance(eng, dict):
                main = eng.get('Main', {})
                tm = main.get('ThrustMax', {}) if isinstance(main, dict) else {}
                t0 = tm.get('ThrustMax0', 'N/A') if isinstance(tm, dict) else 'N/A'
                print(f"  {key}: ThrustMax0={t0} kgf")
    print()

# Su-27 详细检查
fm_su27 = json.load(open('data/raw/su_27.blkx', 'r', encoding='utf-8'))
print("=== Su-27 EngineType0.Main.ThrustMax 字段 ===")
tm = fm_su27.get('EngineType0', {}).get('Main', {}).get('ThrustMax', {})
print(f"ThrustMax0: {tm.get('ThrustMax0')}")
print(f"ThrustMaxCoeff_0_0: {tm.get('ThrustMaxCoeff_0_0')}")
print(f"ThrAftMaxCoeff_0_0: {tm.get('ThrAftMaxCoeff_0_0')}")

# 检查是否有 EngineType1
eng1 = fm_su27.get('EngineType1')
if eng1:
    print(f"\nEngineType1 found!")
    tm1 = eng1.get('Main', {}).get('ThrustMax', {})
    print(f"EngineType1 ThrustMax0: {tm1.get('ThrustMax0')}")
else:
    print("\nNo EngineType1")

# 检查所有顶层键
print(f"\nSu-27 顶层键: {sorted(fm_su27.keys())}")
