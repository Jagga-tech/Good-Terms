STRICTNESS = {"no": 3, "doesnt_say": 2, "yes": 1}
RESULTS = ("still_reading", "says_no", "could_not_read", "meets_all_3", "not_answered_on_pages")


def page_status(labels):
    """Status of a store's pages for one condition, from the labels of its sentences.

    The stricter label wins. A hedged sentence ("unclear") counts as doesnt_say.
    Returns the status and whether the sentences disagree.
    """
    statuses = ["doesnt_say" if label == "unclear" else label for label in labels]
    if not statuses:
        return "doesnt_say", False
    return max(statuses, key=STRICTNESS.__getitem__), len(set(statuses)) > 1


def combine(pages, assistant, pages_disagree=False):
    """The one combining rule. Returns the status shown and the contradiction flag.

    pages: yes, no, doesnt_say, unreadable, pending.
    assistant: yes, no, doesnt_say, unavailable, pending.
    """
    if pages == "pending":
        return "pending", False
    if pages == "yes":
        return ("no", True) if assistant == "no" else ("yes", pages_disagree)
    if pages == "no":
        return "no", assistant == "yes" or pages_disagree
    if assistant == "yes":
        return "assistant_only_yes", pages_disagree
    if assistant == "no":
        return "no", pages_disagree
    return "doesnt_say", pages_disagree


def store_result(rows, pages_read):
    """The one store result. rows carry page_status and status_shown."""
    if not pages_read:
        return "still_reading"
    shown = [row["status_shown"] for row in rows]
    if "no" in shown:
        return "says_no"
    if rows and all(row["page_status"] == "unreadable" for row in rows):
        return "could_not_read"
    if len(shown) == 3 and all(status == "yes" for status in shown):
        return "meets_all_3"
    return "not_answered_on_pages"
