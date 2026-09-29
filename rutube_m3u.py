import requests
import re
import html
import time

BASE = "https://rutube.ru"
WIDGET_URL = f"{BASE}/api/feeds/autowidget/2"
OUTPUT = "rutube.m3u"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://rutube.ru/",
}

PAGE_HEADERS = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def get_json(url, headers=None):
    try:
        r = session.get(
            url,
            headers=headers,
            timeout=30
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  JSON ERROR: {e}")
        return None


def clean_title(title):
    title = title or "Без названия"

    title = re.sub(
        r"^Прямой эфир\s*:?\s*",
        "",
        title,
        flags=re.IGNORECASE
    )

    return title.strip()


def normalize_url(url):
    if not url:
        return None

    url = html.unescape(url)

    url = url.replace("\\/", "/")
    url = url.replace("\\u0026", "&")
    url = url.replace("\\u003F", "?")
    url = url.replace("\\u003f", "?")
    url = url.replace("\\u003D", "=")
    url = url.replace("\\u003d", "=")

    return url.strip()


def extract_m3u8_urls(text):
    if not text:
        return []

    text = html.unescape(text)
    text = text.replace("\\/", "/")
    text = text.replace("\\u0026", "&")
    text = text.replace("\\u003F", "?")
    text = text.replace("\\u003f", "?")
    text = text.replace("\\u003D", "=")
    text = text.replace("\\u003d", "=")

    pattern = re.compile(
        r'https?://[^\'"\s<>\\]+?\.m3u8'
        r'(?:\?[^\'"\s<>\\]*)?',
        re.IGNORECASE
    )

    result = []

    for url in pattern.findall(text):
        url = normalize_url(url)

        if url and url not in result:
            result.append(url)

    return result


def get_api_hls(video_id):
    url = (
        f"{BASE}/api/play/options/"
        f"{video_id}/?format=json"
    )

    data = get_json(url)

    if not data:
        return None

    live_streams = data.get("live_streams") or {}

    if not isinstance(live_streams, dict):
        return None

    hls = live_streams.get("hls")

    if not hls:
        return None

    if isinstance(hls, list):
        for item in hls:
            if not isinstance(item, dict):
                continue

            url = item.get("url")

            if url:
                return normalize_url(url)

    elif isinstance(hls, dict):
        url = hls.get("url")

        if url:
            return normalize_url(url)

    return None


def get_page_hls(video_id):
    """
    Резервный вариант.
    Пытается найти m3u8 непосредственно в HTML страницы.

    Это работает только для случаев, когда URL потока
    действительно присутствует в HTML/встроенном JSON.
    """

    page_url = f"{BASE}/live/video/{video_id}/"

    try:
        r = session.get(
            page_url,
            headers=PAGE_HEADERS,
            timeout=30
        )

        if r.status_code != 200:
            print(f"  PAGE HTTP: {r.status_code}")
            return None

        urls = extract_m3u8_urls(r.text)

        if not urls:
            print("  PAGE: m3u8 не найден")
            return None

        # Если есть master/index — предпочитаем его
        for url in urls:
            if "index.m3u8" in url.lower():
                print(f"  PAGE HLS: {url}")
                return url

        for url in urls:
            if "master.m3u8" in url.lower():
                print(f"  PAGE HLS: {url}")
                return url

        print(f"  PAGE HLS: {urls[0]}")

        return urls[0]

    except Exception as e:
        print(f"  PAGE ERROR: {e}")
        return None


def get_stream(video_id):
    """
    Сначала используем официальный play/options API.
    Если HLS там отсутствует — пробуем страницу live/video.
    """

    url = get_api_hls(video_id)

    if url:
        return url

    print("  API: HLS нет, проверяю страницу")

    return get_page_hls(video_id)


def get_channel_id(item):
    return item.get("id") or item.get("object_id")


def main():
    print("Получаю Rutube autowidget...")

    data = get_json(WIDGET_URL)

    if not data:
        print("Не удалось получить данные Rutube.")
        raise SystemExit(1)

    results = data.get("results", [])

    if not isinstance(results, list):
        print("В ответе отсутствует results.")
        raise SystemExit(1)

    # ---------------------------------------------------------
    # Каналы берём ТОЛЬКО из "Все прямые эфиры"
    # ---------------------------------------------------------

    all_live = None

    for item in results:
        if item.get("name") == "Все прямые эфиры":
            all_live = item
            break

    if not all_live:
        print('Не найдена группа "Все прямые эфиры".')
        raise SystemExit(1)

    childs = all_live.get("childs", [])

    channels = {}

    for item in childs:
        if not isinstance(item, dict):
            continue

        video_id = get_channel_id(item)

        if not video_id:
            continue

        title = (
            item.get("title")
            or item.get("name")
            or item.get("short_title")
            or "Без названия"
        )

        channels[video_id] = {
            "id": video_id,
            "title": clean_title(title),
        }

    print(f'Всего каналов в "Все прямые эфиры": {len(channels)}')

    # ---------------------------------------------------------
    # Группы берём из остальных результатов Rutube
    # ---------------------------------------------------------

    channel_groups = {
        video_id: []
        for video_id in channels
    }

    for group in results:
        group_name = group.get("name")

        if not group_name:
            continue

        if group_name == "Все прямые эфиры":
            continue

        group_childs = group.get("childs", [])

        if not isinstance(group_childs, list):
            continue

        for item in group_childs:
            if not isinstance(item, dict):
                continue

            video_id = get_channel_id(item)

            if video_id not in channel_groups:
                continue

            if group_name not in channel_groups[video_id]:
                channel_groups[video_id].append(group_name)

    # ---------------------------------------------------------
    # Получаем HLS
    # ---------------------------------------------------------

    streams = {}

    total = len(channels)

    for number, (video_id, channel) in enumerate(
        channels.items(),
        start=1
    ):
        print(
            f"\n[{number}/{total}] {channel['title']}"
        )

        stream = get_stream(video_id)

        if stream:
            streams[video_id] = stream
            print(f"  HLS: {stream}")
        else:
            print(
                f"  STREAM: НЕТ  ID={video_id}"
            )

        time.sleep(0.1)

    # ---------------------------------------------------------
    # Формируем M3U
    # ---------------------------------------------------------

    lines = [
        "#EXTM3U"
    ]

    records = 0

    for video_id, channel in channels.items():

        stream = streams.get(video_id)

        if not stream:
            continue

        title = channel["title"]
        groups = channel_groups.get(video_id, [])

        if groups:
            for group in groups:

                lines.append(
                    f'#EXTINF:-1 group-title="{group}",{title}'
                )

                lines.append(stream)

                records += 1

        else:
            lines.append(
                f"#EXTINF:-1,{title}"
            )

            lines.append(stream)

            records += 1

    # ---------------------------------------------------------
    # Записываем
    # ---------------------------------------------------------

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "\n".join(lines) + "\n"
        )

    print()
    print("=" * 60)
    print(f"Всего каналов: {total}")
    print(f"Доступно HLS: {len(streams)}")
    print(f"Записей M3U: {records}")
    print(f"Файл: {OUTPUT}")
    print("=" * 60)

    # Если вообще ничего не получили — считаем запуск ошибочным.
    # Тогда GitHub Actions не будет затирать рабочий файл пустым M3U.
    if not streams:
        print("ОШИБКА: не найден ни один HLS-поток.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()