import re


def format_build_finished_status(status, texts):
    status_text = texts["network_build_done"].format(
        new_vectors=int(status.get("new_vectors", 0)),
        total_vectors=int(status.get("total_vectors", 0)),
    )

    if int(status.get("new_vectors", 0)) == 0:
        status_text = f"{status_text} {texts['network_build_no_new']}"

    failed_count = int(status.get("failed_count", 0))
    if failed_count > 0:
        status_text = f"{status_text} {texts['network_build_failed_count'].format(count=failed_count)}"

    summary_text = texts["network_build_summary"].format(
        success=int(status.get("success_count", 0)),
        failed=failed_count,
        skipped=int(status.get("skipped_count", 0)),
    )
    report_path = str(status.get("report_path", "") or "").strip()
    if report_path:
        return f"{status_text} {summary_text} {texts['network_build_report_path'].format(path=report_path)}"
    return f"{status_text} {summary_text}"


def format_build_progress_text(raw_text, texts):
    text = str(raw_text or "")

    preparing = re.match(r"^Preparing source (\d+)/(\d+)$", text)
    if preparing:
        return texts["network_build_progress_preparing"].format(
            current=int(preparing.group(1)),
            total=int(preparing.group(2)),
        )

    resolving = re.match(r"^Resolving source (\d+)/(\d+)$", text)
    if resolving:
        return texts["network_build_progress_resolving"].format(
            current=int(resolving.group(1)),
            total=int(resolving.group(2)),
        )

    extracting = re.match(r"^Extracting frames (\d+)/(\d+)$", text)
    if extracting:
        return texts["network_build_progress_extracting"].format(
            current=int(extracting.group(1)),
            total=int(extracting.group(2)),
        )

    embedding = re.match(r"^Embedding frames (\d+)/(\d+)$", text)
    if embedding:
        return texts["network_build_progress_embedding"].format(
            current=int(embedding.group(1)),
            total=int(embedding.group(2)),
        )

    merging = re.match(r"^Merging vectors (\d+)/(\d+)$", text)
    if merging:
        return texts["network_build_progress_merging"].format(
            current=int(merging.group(1)),
            total=int(merging.group(2)),
        )

    indexed = re.match(r"^Indexed (\d+) frames from source (\d+)/(\d+)$", text)
    if indexed:
        return texts["network_build_progress_indexed"].format(
            frames=int(indexed.group(1)),
            current=int(indexed.group(2)),
            total=int(indexed.group(3)),
        )

    skipped = re.match(r"^Skipped source (\d+)/(\d+)$", text)
    if skipped:
        return texts["network_build_progress_skipped"].format(
            current=int(skipped.group(1)),
            total=int(skipped.group(2)),
        )

    if text == "Building FAISS index":
        return texts["network_build_progress_building"]
    if text == "Remote library build completed":
        return texts["network_build_progress_completed"]
    return text
