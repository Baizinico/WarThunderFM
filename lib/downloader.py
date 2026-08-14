"""War Thunder 飞行模型数据下载模块。

从 jsdelivr CDN 下载 gszabi99/War-Thunder-Datamine 仓库中的 .blkx JSON 文件，
提供缓存判断与临时网络故障重试机制。
"""

import sys
import urllib.error
import urllib.request
from pathlib import Path

# jsdelivr CDN 上 flightmodels/fm 目录的基址
CDN_BASE = (
    "https://cdn.jsdelivr.net/gh/gszabi99/War-Thunder-Datamine@master"
    "/aces.vromfs.bin_u/gamedata/flightmodels/fm"
)

# 默认的原始数据存放目录
DEFAULT_RAW_DIR = Path("data/raw")


def download_fm(aircraft: str, dest_dir: Path) -> Path:
    """下载指定飞机的 .blkx 飞行模型文件。

    参数:
        aircraft: 飞机代号，例如 ``j_10c``、``f-16a`` 等。
        dest_dir: 目标目录（通常是 ``data/raw/``），不存在时会自动创建。

    返回:
        下载后保存的本地文件路径 ``dest_dir/<aircraft>.blkx``。

    说明:
        - 若目标文件已存在，则跳过下载并打印 "已缓存" 信息。
        - 首次下载因临时网络故障（``urllib.error.URLError``）失败时会重试一次；
          若仍失败则抛出异常。证书校验始终开启（不会降级为 CERT_NONE）。
        - 下载成功时会打印文件大小（KB 或 MB）。
    """
    # 确保目标目录存在
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / f"{aircraft}.blkx"

    # 缓存判断：文件已存在则直接返回
    if dest_path.exists():
        print(f"已缓存: {dest_path}")
        return dest_path

    url = f"{CDN_BASE}/{aircraft}.blkx"

    # 第一次尝试（证书校验开启）
    try:
        data = _fetch(url)
    except urllib.error.URLError as first_err:
        print(f"首次下载失败（{type(first_err).__name__}: {first_err}），重试...")
        # 第二次尝试：仅重试，不降低任何安全校验
        try:
            data = _fetch(url)
        except urllib.error.URLError as second_err:
            raise RuntimeError(
                f"下载 {aircraft} 失败：{type(second_err).__name__}: {second_err}。"
                f"请检查网络连接或确认飞机代号是否正确（URL: {url}）。"
            ) from second_err

    # 写入文件
    dest_path.write_bytes(data)

    # 打印文件大小
    size_bytes = len(data)
    if size_bytes >= 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        size_str = f"{size_bytes / 1024:.2f} KB"
    print(f"已下载: {dest_path} ({size_str})")

    return dest_path


def _fetch(url: str) -> bytes:
    """通过 urllib.request 获取 URL 内容并返回字节数据。

    参数:
        url: 要下载的 URL。

    返回:
        URL 响应体的原始字节数据。
    """
    req = urllib.request.Request(url, headers={"User-Agent": "WarThunderFM-Downloader/1.0"})
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def main(argv: list[str]) -> int:
    """命令行入口，允许 ``python lib/downloader.py j_10c`` 进行测试。

    参数:
        argv: 命令行参数列表（不含脚本名）。

    返回:
        进程退出码，0 表示成功，1 表示失败。
    """
    if len(argv) < 1:
        print(f"用法: python {Path(__file__).name} <aircraft> [dest_dir]")
        print(f"示例: python {Path(__file__).name} j_10c")
        return 1

    aircraft = argv[0]
    dest_dir = Path(argv[1]) if len(argv) >= 2 else DEFAULT_RAW_DIR

    try:
        path = download_fm(aircraft, dest_dir)
        print(f"完成: {path}")
        return 0
    except Exception as e:  # noqa: BLE001 - 入口处统一兜底
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
