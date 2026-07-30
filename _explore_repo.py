"""探索 WT Datamine 仓库结构，找到国家归属数据位置。"""
import urllib.request
import json

url = 'https://api.github.com/repos/gszabi99/War-Thunder-Datamine/contents/aces.vromfs.bin_u/gamedata/units/flightmodels'
req = urllib.request.Request(url, headers={'User-Agent': 'WT', 'Accept': 'application/vnd.github+json'})
data = json.loads(urllib.request.urlopen(req, timeout=30).read())
for item in data:
    t = '[DIR] ' if item['type'] == 'dir' else '[FILE]'
    print(f"{t} {item['name']}")
