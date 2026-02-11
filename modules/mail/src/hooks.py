from logging import LoggerAdapter
from pathlib import Path
from typing import Literal, Optional

from cellophane import Config, Samples, Timestamp, post_hook, pre_hook

from .util import render_mail, resolve_attachments, send_mail


def _mail_hook(
    samples: Samples,
    logger: LoggerAdapter,
    config: Config,
    workdir: Path,
    when: Literal["start", "end"],
    timestamp: Optional[Timestamp] = None,
    **_,
):
    if not samples:
        logger.info(f"No samples to send {when} mail for")
        return samples

    if not config.mail.send:
        logger.info("Mail is disabled")
        return samples

    logger.info(f"Sending {when} mail")
    subject, body = render_mail(
        subject=config.mail[when].subject,
        body=config.mail[when].body,
        samples=samples,
        config=config,
        timestamp=timestamp,
    )

    attachments = resolve_attachments(
        attachments=samples.mail_attachments | {*config.mail[when].attachments},
        logger=logger,
        samples=samples,
        config=config,
    )

    if when == "end":
        attachments |= resolve_attachments(
            attachments=config.mail[when].attachments_complete,
            logger=logger,
            samples=samples.complete,
            config=config,
        )

        attachments |= resolve_attachments(
            attachments=config.mail[when].attachments_failed,
            logger=logger,
            samples=samples.failed,
            config=config,
        )

    logger.debug(f"Subject: {subject}")
    logger.debug(f"From: {config.mail.from_addr}")
    for to in config.mail.to_addr:
        logger.debug(f"To: {to}")
    for cc in config.mail.get("cc_addr", []):
        logger.debug(f"Cc: {cc}")
    for a in attachments:
        logger.debug(f"Attachment: {a}")
    logger.debug(f"Body:\n{body}")

    send_mail(
        **config.mail.smtp,
        body=body,
        subject=subject,
        to_addr=config.mail.to_addr,
        from_addr=config.mail.from_addr,
        cc_addr=config.mail.get("cc_addr"),
        attachments=attachments,
        attachment_parent=workdir,
    )

    return samples


@pre_hook(label="Send start mail", after="all")
def start_mail(
    samples: Samples,
    logger: LoggerAdapter,
    config: Config,
    workdir: Path,
    **_,
):
    """Send a mail at the start of the analysis"""
    return _mail_hook(
        samples=samples,
        logger=logger,
        config=config,
        workdir=workdir,
        when="start",
    )


@post_hook(label="Send end mail", condition="always", after="all")
def end_mail(
    samples: Samples,
    logger: LoggerAdapter,
    config: Config,
    workdir: Path,
    timestamp: Timestamp,
    **_,
):
    """Send a mail at the end of the analysis"""
    return _mail_hook(
        samples=samples,
        logger=logger,
        config=config,
        workdir=workdir,
        when="end",
        timestamp=timestamp,
    )
