"""批量下载全部 War Thunder 飞行模型 .blkx 文件。

从 jsdelivr CDN 并发下载所有 .blkx 文件到 data/raw/ 目录。
已缓存的文件自动跳过。支持断点续传。
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, ".")
from lib.downloader import download_fm, DEFAULT_RAW_DIR

LIST_FILE = Path("data/_all_aircraft.txt")
RAW_DIR = Path("data/raw")
MAX_WORKERS = 16  # 并发下载数


def download_one(aircraft: str) -> tuple[str, bool, str]:
    """下载单个飞机模型。返回 (aircraft, success, message)。"""
    try:
        path = download_fm(aircraft, RAW_DIR)
        return aircraft, True, str(path)
    except Exception as e:  # noqa: BLE001
        return aircraft, False, str(e)


def main():
    # 读取飞机列表
    if not LIST_FILE.exists():
        print(f"✗ 找不到文件列表: {LIST_FILE}", file=sys.stderr)
        return 1

    names = [n.strip() for n in LIST_FILE.read_text(encoding="utf-8").splitlines() if n.strip()]
    total = len(names)
    print(f"共 {total} 个飞机模型待下载")
    print(f"目标目录: {RAW_DIR}")
    print(f"并发数: {MAX_WORKERS}")
    print()

    # 统计已缓存数量
    cached = sum(1 for n in names if (RAW_DIR / f"{n}.blkx").exists())
    print(f"已缓存: {cached}，待下载: {total - cached}")
    print()

    success_count = 0
    fail_count = 0
    fail_list = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_one, name): name for name in names}
        done = 0
        for future in as_completed(futures):
            aircraft, ok, msg = future.result()
            done += 1
            if ok:
                success_count += 1
            else:
                fail_count += 1
                fail_list.append((aircraft, msg))
            # 每 100 个打印进度
            if done % 100 == 0 or done == total:
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"进度: {done}/{total} ({done*100//total}%)  "
                      f"成功={success_count} 失败={fail_count}  "
                      f"速率={rate:.1f}/s  剩余≈{eta:.0f}s")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"下载完成！耗时 {elapsed:.1f}s")
    print(f"成功: {success_count}  失败: {fail_count}  总计: {total}")

    if fail_list:
        print(f"\n失败列表（{len(fail_list)} 个）:")
        for name, msg in fail_list[:20]:
            print(f"  ✗ {name}: {msg}")
        if len(fail_list) > 20:
            print(f"  ... 还有 {len(fail_list)-20} 个")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
