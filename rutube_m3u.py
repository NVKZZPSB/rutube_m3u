
import time
import requests

WIDGET_URL = "https://rutube.ru/api/feeds/autowidget/2"
OUTPUT_FILE = "rutube.m3u"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://rutube.ru/",
}

session = requests.Session()
session.headers.update(HEADERS)


def clean_title(title):
    title = title.strip()

    for prefix in (
        "Прямой эфир: ",
        "Прямой эфир ",
    ):
        if title.startswith(prefix):
            title = title[len(prefix):]

    return title.strip()


def get_widget():
    print("Получаю Rutube autowidget...")

    r = session.get(WIDGET_URL, timeout=20)
    r.raise_for_status()

    return r.json()


def get_hls(video_id):
    url = (
        f"https://rutube.ru/api/play/options/{video_id}/"
        f"?format=json&no_404=true&referer=https%3A%2F%2Frutube.ru%2F"
    )

    try:
        r = session.get(url, timeout=10)

        if r.status_code != 200:
            print(f"  API: HTTP {r.status_code}")
            return None

        data = r.json()

    except requests.RequestException as e:
        print(f"  API ERROR: {e}")
        return None

    except ValueError:
        print("  API ERROR: неверный JSON")
        return None

    live_streams = data.get("live_streams") or {}
    hls = live_streams.get("hls") or []

    if not hls:
        return None

    # Берём именно master HLS.
    for item in hls:
        stream_url = item.get("url")

        if stream_url:
            return stream_url

    return None


def main():
    data = get_widget()

    results = data.get("results") or []

    all_live = None

    # Ищем именно "Все прямые эфиры".
    for group in results:
        if group.get("name") == "Все прямые эфиры":
            all_live = group
            break

    if not all_live:
        raise RuntimeError('Не найден раздел "Все прямые эфиры"')

    channels = all_live.get("childs") or []

    print(f'Всего каналов в "Все прямые эфиры": {len(channels)}')
    print()

    # ------------------------------------------------------------
    # Собираем группы каждого канала.
    #
    # Формат:
    # channel_groups[video_id] = [
    #     "Федеральные",
    #     "Новости",
    #     ...
    # ]
    # ------------------------------------------------------------

    channel_groups = {}

    for group in results:
        group_name = (group.get("name") or "").strip()

        if not group_name:
            continue

        if group_name == "Все прямые эфиры":
            continue

        for channel in group.get("childs") or []:
            video_id = channel.get("id")

            if not video_id:
                continue

            channel_groups.setdefault(video_id, [])

            if group_name not in channel_groups[video_id]:
                channel_groups[video_id].append(group_name)

    playlist = []
    streams_found = 0

    playlist.append("#EXTM3U")
    playlist.append("")

    for index, channel in enumerate(channels, 1):

        video_id = channel.get("id")

        if not video_id:
            continue

        raw_title = (
            channel.get("name")
            or channel.get("title")
            or "Без названия"
        )

        title = clean_title(raw_title)

        print(f"[{index}/{len(channels)}] {title}")

        hls_url = get_hls(video_id)

        if not hls_url:
            print(f"  STREAM: НЕТ  ID={video_id}")
            print()
            continue

        print(f"  HLS: {hls_url}")

        groups = channel_groups.get(video_id, [])

        # --------------------------------------------------------
        # Как в версии для ПК:
        # один и тот же канал добавляется отдельно для каждой
        # группы RUTUBE.
        # --------------------------------------------------------

        if groups:
            for group_name in groups:
                playlist.append(
                    f'#EXTINF:-1 group-title="{group_name}",{title}'
                )
                playlist.append(hls_url)
                playlist.append("")

        else:
            # Если RUTUBE не присвоил каналу тематическую группу,
            # всё равно сохраняем канал.
            playlist.append(
                f'#EXTINF:-1 group-title="Без группы",{title}'
            )
            playlist.append(hls_url)
            playlist.append("")

        streams_found += 1

        # Небольшая пауза между запросами.
        time.sleep(0.1)

    if streams_found == 0:
        raise RuntimeError(
            "Не найдено ни одного HLS-потока. "
            "rutube.m3u не изменён."
        )

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(playlist))

    print()
    print(f"Готово.")
    print(f"Каналов с HLS: {streams_found}")
    print(f"Файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

