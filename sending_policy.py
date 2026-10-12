"""Dry-run policy specification for a later official sender. Never sends messages."""
from datetime import timedelta

def sending_blockers(*, approved, live_enabled, connection_approved, opt_in, opted_out,
                     last_customer_message, at, template_approved=False, closed_deal=False):
    blockers=[]
    if not approved: blockers.append('Human approval required')
    if not live_enabled: blockers.append('Live sending disabled')
    if not connection_approved: blockers.append('Owner has not approved the official connection')
    if not opt_in or opted_out: blockers.append('Consent missing or customer opted out')
    if closed_deal: blockers.append('Won/Lost deal: sales follow-ups stopped')
    in_window=bool(last_customer_message and at-timedelta(hours=24)<last_customer_message<=at)
    if not in_window and not template_approved: blockers.append('Outside customer-service window: approved template required')
    return blockers
