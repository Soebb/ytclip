"""
    Downloads and clips videos from youtube, rumble, bitchute (using yt-dlp) and clips
    the video using ffmpeg.
"""

import os
import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

from ytclip.version import VERSION

LOG = True


def set_logging(val: bool) -> None:
    """Sets the logging state, which is the file created for each command."""
    global LOG  # pylint: disable=global-statement
    LOG = val


def _find_video_file_from_stdout(stdout: str) -> Optional[str]:
    value = None
    for line in stdout.splitlines():
        # File pattern # 1
        needle = '[Merger] Merging formats into "'
        if needle in line:
            value = line.replace(needle, "").replace('"', "")
            continue
        # File pattern # 2 (found in brighteon)
        needle = "[download] Destination: "
        if needle in line:
            value = line.replace(needle, "")
            continue
    return value


def _exec(cmd_str: str) -> Tuple[int, str, str]:
    proc_yt = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd_str,
        shell=True,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc_yt.communicate()
    assert proc_yt.returncode is not None
    return proc_yt.returncode, stdout, stderr


def _append_file(filepath: str, data: str):
    with open(filepath, encoding="utf-8", mode="a+") as filed:
        filed.write(data)


def run_download_and_cut(
    url: str, start_timestamp: str, length: str, outname: str
) -> None:
    """Runs a series of commands that downloads and cuts the given url to output filename."""
    if LOG:
        outlog = os.path.join("log", outname + ".log")
        os.makedirs(os.path.dirname(outlog), exist_ok=True)
    yt_dlp_cmd: str = f"yt-dlp --no-check-certificate --force-overwrites {url}"
    returncode, stdout, stderr = _exec(yt_dlp_cmd)
    if LOG:
        _append_file(
            outlog, f"{yt_dlp_cmd} returned {returncode}\n\n {stdout+stderr}\n"
        )
    # Search through the output of the yt-dlp command to for the
    # file name.
    fullvideo = _find_video_file_from_stdout(stdout + stderr)
    if fullvideo is None or not os.path.exists(fullvideo):
        raise OSError(
            f"Could not find a video in \n"
            "###################\n"
            f"{stdout}"
            "\n###################\n"
            f"with command '{yt_dlp_cmd}'\n"
            f"RETURNED: {returncode}\n"
        )
    ffmpeg_cmd = (
        f'static_ffmpeg -y -i "{fullvideo}"'  # accepts any prompts with y
        # start timestamp (seconds or h:mm:ss:ff)
        f" -ss {start_timestamp}"
        # length timestamp (seconds or h:mm:ss:ff)
        f" -t {length}"
        f" {outname}.mp4"
    )
    returncode, stdout, stderr = _exec(ffmpeg_cmd)
    if LOG:
        _append_file(outlog, f"{ffmpeg_cmd} returned {returncode}\n\n{stdout+stderr}\n")
    if returncode != 0:
        raise OSError(
            f"Error running {ffmpeg_cmd}."
            "###################\n"
            f"STDOUT:\n{stdout}\n"
            "\n###################\n"
            f"STDERR:\n{stderr}\n"
            "\n###################\n"
            f"with command '{yt_dlp_cmd}'\n"
        )
    os.remove(fullvideo)


def _finish_then_print_completion(future):
    try:
        future.result()
        print(f'Finished job "{future.url}"')
    except BaseException as berr:  # pylint: disable=broad-except
        print(
            f'ERROR fetching clip from "{future.url}" because of error:\n' f"{berr}\n"
        )


def unit_test_brighteon():
    """Unit test for brighteon."""
    run_download_and_cut(
        "https://www.brighteon.com/f596cc8b-4b52-4152-92cb-39dadc552833",
        "10:47",
        "20",
        "health_ranger_report",
    )


def unit_test_bitchute():
    """Unit test for bitchute."""
    run_download_and_cut(
        "https://www.bitchute.com/video/pDCS8i20enIq",
        "08:08",
        "20",
        "sarah_westhall",
    )


def run_cmd():
    """Entry point for the command line "ytclip" utilitiy."""
    global LOG  # pylint: disable=global-statement
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "only run the tool once (useful for automation)\n"
            "Example:\n"
            "(echo 'http://www.youtube.com/watch?v=-wtIMTCHWuI'; echo '08:59'; echo '15'; echo './myoutput') | ytclip --once\n"  # pylint: disable=line-too-long
        ),
    )
    parser.add_argument(
        "--version", action="store_true", help=f"print version {VERSION}"
    )
    parser.add_argument(
        "--no-log", action="store_true", help="suppresses log file if set"
    )
    args = parser.parse_args()
    if args.version:
        print(f"{VERSION}")
        sys.exit(0)
    if args.no_log:
        LOG = False
    futures = []
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        while True:
            print("Add new video:")
            url = input("  url: ")
            if url != "":
                start_timestamp = input("  start_timestamp: ")
                length = input("  length: ")
                output_name = input("  output_name: ")

                def task():
                    return run_download_and_cut(
                        url=url,
                        start_timestamp=start_timestamp,
                        length=length,
                        outname=output_name
                    )

                f = executor.submit(task)  # pylint: disable=invalid-name
                setattr(f, "url", url)
                setattr(f, "name", output_name)
                futures.append(f)
                print(f"\nStarting {url} in background.\n")
            # Have any futures completed?
            finished_futures = [
                f for f in futures if f.done()  # pylint: disable=invalid-name
            ]
            futures = [f for f in futures if f not in finished_futures]
            for f in finished_futures:  # pylint: disable=invalid-name
                _finish_then_print_completion(f)
            out_str = f"There are {len(futures)} jobs outstanding:\n"
            if len(futures):
                for f in futures:  # pylint: disable=invalid-name
                    out_str += f"\n  {f.name}"
                out_str += "\n"
            out_str += "\n"
            print(out_str)

            if args.once:
                break

    except KeyboardInterrupt:
        print("\n\n")

    unfinished_futures = [f for f in futures if not f.done()]
    if unfinished_futures:
        print(f"Waiting for {len(unfinished_futures)} commands to finish")
        for i, f in enumerate(unfinished_futures):  # pylint: disable=invalid-name
            sys.stdout.write(f"  Waiting for {f.url} to finish...\n")
            while not f.done():
                time.sleep(0.1)
            _finish_then_print_completion(f)
            sys.stdout.write(f"  ... done, {len(unfinished_futures)-i} left\n")
    print("All commands completed.")


def main():
    """Just defaults to run_cmd."""
    run_cmd()


if __name__ == "__main__":
    # unit_test_brighteon()
    # unit_test_stdout_parse()
    # unit_test_bitchute()
    main()
