import json
fm = json.load(open('data/raw/j_10c.blkx', 'r', encoding='utf-8'))
wp = fm['Aerodynamics']['WingPlane']
print('Span:', wp.get('Span'))
print('Areas:', wp.get('Areas'))
print('SweptAngle:', wp.get('SweptAngle'))
print()
p = wp['FlapsPolar0']
print('=== Mach channel 1 ===')
print('MachCrit1:', p.get('MachCrit1'), 'MachMax1:', p.get('MachMax1'),
      'MultMachMax1:', p.get('MultMachMax1'), 'MultLimit1:', p.get('MultLimit1'),
      'MultLineCoeff1:', p.get('MultLineCoeff1'), 'MachFactor:', p.get('MachFactor'))
print()
print('=== Mach channel 2 ===')
print('MachCrit2:', p.get('MachCrit2'), 'MachMax2:', p.get('MachMax2'), 'MultMachMax2:', p.get('MultMachMax2'))
print()
print('=== Mach channel 7 ===')
print('MachCrit7:', p.get('MachCrit7'), 'MachMax7:', p.get('MachMax7'), 'MultMachMax7:', p.get('MultMachMax7'))
print()
print('=== Check MachCrit0 exists? ===')
print('MachCrit0:', p.get('MachCrit0'), 'MachMax0:', p.get('MachMax0'), 'MultMachMax0:', p.get('MultMachMax0'))
print()
print('=== Fuselage ===')
fp = fm['Aerodynamics'].get('FuselagePlane', {})
print('Fuselage keys:', list(fp.keys()))
print('Fuselage Areas:', fp.get('Areas'))
print('Fuselage.Polar CdMin:', fp.get('Polar', {}).get('CdMin'))
print()
print('=== HorStab / VerStab ===')
for k in ['HorStabPlane', 'VerStabPlane']:
    pl = fm['Aerodynamics'].get(k, {})
    print(k, 'Areas:', pl.get('Areas'), 'Span:', pl.get('Span'))
    print('  Polar CdMin:', pl.get('Polar', {}).get('CdMin'))
