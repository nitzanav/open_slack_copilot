from common.slack.mrkdwn_convert import to_slack_mrkdwn


def test_bold_double_asterisks_to_slack_bold():
    src = "**Merchant name:** 88bd2d-3\n**Status:** Waiting-for"
    out = to_slack_mrkdwn(src)
    assert out == "*Merchant name:* 88bd2d-3\n*Status:* Waiting-for"


def test_atx_headers_to_bold_lines():
    src = "### This week\n- item"
    out = to_slack_mrkdwn(src)
    assert out.startswith("*This week*\n")


def test_code_spans_unchanged():
    src = "Use `**not bold**` and ```\n**also not bold**\n```"
    assert to_slack_mrkdwn(src) == src


def test_idempotent_on_slack_bold():
    src = "*Merchant name:* value"
    assert to_slack_mrkdwn(src) == src
