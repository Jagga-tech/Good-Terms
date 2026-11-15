"""Every status and result wording the screens show. The web app holds none of these."""

STILL_READING = "Still reading this store's pages"
COULD_NOT_READ = "We couldn't read this store's pages"


def status_text(shown, page_status):
    if shown == "pending":
        return STILL_READING
    if shown == "yes":
        return "Yes"
    if shown == "assistant_only_yes":
        if page_status == "unreadable":
            return "Store's assistant says yes. We couldn't read its pages."
        return "Store's assistant says yes. Not found on its pages."
    if shown == "no":
        return "No" if page_status == "no" else "Store's assistant says no."
    return "Doesn't say"


def pages_text(page_status, has_sentences, read_note):
    """Plain words for the place of the store's own words when there is no sentence to show."""
    if page_status == "pending":
        return STILL_READING
    if read_note:
        return read_note
    if page_status == "unreadable":
        return COULD_NOT_READ
    if not has_sentences:
        return "This store's pages say nothing about this."
    return None


def contradiction_text(pages_disagree, sources_contradict):
    parts = []
    if pages_disagree:
        parts.append("This store's pages say different things.")
    if sources_contradict:
        parts.append("This store's pages and its assistant contradict each other.")
    return " ".join(parts) or None


def result_text(result, rows):
    if result == "still_reading":
        return STILL_READING
    if result == "meets_all_3":
        return "Meets all 3 of your conditions"
    if result == "says_no":
        count = sum(row["status_shown"] == "no" for row in rows)
        return f"Says no to {count} of your conditions"
    if result == "could_not_read":
        return COULD_NOT_READ
    if result == "not_answered_on_pages":
        count = sum(row["status_shown"] != "yes" for row in rows)
        verb = "is" if count == 1 else "are"
        return f"{count} of your conditions {verb} not answered on its pages. That is not a yes."
    return "Not checked"


def dollars(cents):
    return f"${cents // 100:,}.{cents % 100:02d}"


def price_gap(stores):
    """The price-gap line: two prices and their difference, nothing more."""
    priced = [store for store in stores if store.get("offer")]
    if not priced:
        return None
    price = lambda store: store["offer"]["price_cents"]
    cheapest = min(priced, key=price)
    meeting = [store for store in priced if store["result"] == "meets_all_3"]
    gap = {
        "cheapest": {"name": cheapest["name"], "price_cents": price(cheapest)},
        "cheapest_meeting_all_3": None,
        "difference_cents": None,
    }
    line = f"Cheapest overall: {dollars(price(cheapest))} at {cheapest['name']}."
    if not meeting:
        gap["text"] = f"{line} No store says yes to all 3 of your conditions."
        return gap
    best = min(meeting, key=price)
    gap["cheapest_meeting_all_3"] = {"name": best["name"], "price_cents": price(best)}
    gap["difference_cents"] = price(best) - price(cheapest)
    if best is cheapest:
        gap["text"] = f"{line} It also says yes to all 3 of your conditions."
        return gap
    gap["text"] = (
        f"{line} Cheapest that says yes to all 3 of your conditions: {dollars(price(best))}"
        f" at {best['name']}. Difference: {dollars(gap['difference_cents'])}."
    )
    return gap
