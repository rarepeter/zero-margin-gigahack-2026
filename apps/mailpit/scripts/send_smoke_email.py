#!/usr/bin/env python3
"""Send one non-sensitive SMTP smoke-test message to the local Mailpit inbox.

This script deliberately exercises only the Mailpit SMTP service. It is not
called by the Secure MOM pipeline and contains no meeting-derived content.
"""

from __future__ import annotations

import argparse
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--from", dest="sender", default="secure-mom@medpark.test")
    parser.add_argument("--to", dest="recipient", default="demo.recipient@medpark.test")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    message = EmailMessage()
    message["From"] = args.sender
    message["To"] = args.recipient
    message["Subject"] = "Secure MOM — local Mailpit SMTP check"
    message["Message-ID"] = make_msgid(domain="medpark.test")
    message.set_content(
        "This is a non-sensitive local SMTP smoke test. "
        "No meeting data is included."
    )

    with smtplib.SMTP(args.host, args.port, timeout=5) as smtp:
        smtp.send_message(message)

    print(
        "Mailpit accepted the test message for "
        f"{args.recipient}. Open http://127.0.0.1:8025 to inspect it."
    )


if __name__ == "__main__":
    main()
