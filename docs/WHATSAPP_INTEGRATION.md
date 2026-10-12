# MYWAY WhatsApp assistant: plan and safe prototype

## Your current CRM is preserved

The original customers, quotations, PDFs, login and Day 2/5/10 reminder code remain in place. The assistant creates additional SQLite tables with `CREATE TABLE IF NOT EXISTS`. It does not replace existing tables or automatically turn uncertain conversations into quotations. The sample conversations have no phone numbers, are labelled Demo, and are separate from real CRM records. Existing uncommitted application files were kept.

## What is available now

After restarting the application, sign in using your existing login. Open **Sales Assistant**, press **Load sample conversations**, and examine the nine fictional conversations. Repeated loads do not duplicate them. Categories are Karaoke, Indoor LED, Outdoor LED, LED Poster, Pro Sound, Home Theater, Smart Home, Technical Support and Other.

The assistant suggests a category and sales state, displays the supporting conversation and flags potential urgency. You can correct category/state. **Prepare message for approval** creates an English, Chinese or Bahasa Melayu draft personalized with the sample customer and product category. The Approval Queue lets you edit, approve or reject it. Approval stores your decision, reviewer and time; it sends nothing. There is no assistant send route, API token, webhook listener or network client.

This stage is an **offline rules prototype**, not a connected AI model. It is suitable for testing the workflow, not making autonomous sales decisions. Category detection is keyword-based, can recognize multiple categories, and prefers Technical Support when troubleshooting words are found. It can miss slang, mixed languages, negation, unsupported number formats and subtle pricing terms. Urgency may persist from older chat language; review it yourself.

Quotation detection intentionally distinguishes:

- Customer budgets, “how much”, starting prices and rough estimates: general price discussions.
- Business-authored explicit price offers: informal offer candidates.
- PDF text containing quotation wording, an identifier and an RM amount: formal-PDF candidates.
- PDFs without sufficient evidence: needs review. A filename containing “quotation” is insufficient.

PDF extraction in these samples is supplied fictional text, not real file parsing. Incoming competitor PDFs are not marked as MYWAY quotations. “Quotation received” means a candidate was sent in the sample conversation, not a verified delivery/read receipt. Candidate quotation counts are separate from existing confirmed CRM quotation totals. Customer replies take precedence over follow-up suggestions. No uncertain amount or document changes a real quotation or existing reminder.

## 5 PM Malaysia summary

Daily summaries are stored locally, once per calendar date, with a **17:00 Asia/Kuala_Lumpur** cutoff. They show new enquiries, customers who sent messages today, currently unanswered customers, today's outbound quotation/offer candidates, follow-up suggestions and possible urgent opportunities. The page explains each metric. A provisional view uses events available by the current time, capped at 5 PM. Saved summaries use events up to 5 PM and remain unchanged.

For automatic generation, keep the application running and start this second process in the same repository and with the same `CRM_DATA_DIR`:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe summary_worker.py
```

Linux/cloud:

```sh
.venv/bin/python summary_worker.py
```

The worker checks every 30 seconds and saves the summary at or shortly after 5 PM. Stop with Ctrl+C. No notification or WhatsApp message is sent. A sleeping/offline computer cannot generate an exact-time summary; the worker or the assistant page saves today's snapshot on the next check after 5 PM. It does not backfill earlier missed dates. Run the worker as a restartable service on an always-on host for reliable daily operation. Alternatively schedule `.venv/bin/python -m flask --app app assistant-summary` at 17:00 Malaysia time (09:00 UTC). Do not schedule a Windows task in UTC if the computer already uses Malaysia time.

Loading sample data after an existing summary does not rewrite that snapshot. Tomorrow's summary reflects retained sample conversations. When a live connector is implemented, the summary must distinguish late-arriving messages and incomplete synchronization.

## Proposed live architecture

1. **Official onboarding:** connect an eligible number through Meta's official Cloud API/Embedded Signup flow, with Coexistence supported by the selected provider if eligible. Do not delete or migrate the current Business app account just to test eligibility.
2. **Verified event receiver:** public HTTPS endpoint verifies Meta's challenge and webhook signature, checks account/phone scope, persists raw events and deduplicates by message/event identifier. Credentials belong in secure environment settings, never Git or chat.
3. **Durable processing:** acknowledge quickly after durable persistence, then process retries asynchronously. Normalize message direction, sender, timestamps, delivery status and supported app-sent echoes. Do not infer receipt from an outbound message alone.
4. **Conversation-to-CRM linking:** match verified WhatsApp contact identifiers to normalized numbers, automatically create new customer candidates, and ask for review when identity is ambiguous. Update existing records carefully; keep provenance and do not overwrite manual notes/categories. Real contact creation is a later connector stage.
5. **Quotation/media pipeline:** retrieve official media through authenticated APIs, validate size/type, store PDFs privately, extract text/OCR safely, and distinguish brochures and competitor quotes from MYWAY offers. Extract number, currency, scope and validity with evidence. Human confirmation links a real CRM quotation and starts its existing reminders; uncertain price talk never creates a Sent quotation.
6. **AI analysis:** choose a model/provider and data-retention terms before sharing real customer chats. Treat all chat/PDF content as untrusted input; it must not invoke tools or send messages. Return structured category, state, evidence and uncertainty. Minimize/redact unnecessary personal data and provide correction and audit history. The current offline analyzer is a tested baseline, not a substitute for this.
7. **Approval and official outbox:** approval references the exact edited message and conversation version. A separate sender rechecks consent/opt-out, current customer-service window, approved template, conversation changes, Won/Lost suppression, duplicates, rate limits and owner authorization immediately before sending. Store API outcomes and retry safely; uncertain delivery cannot trigger duplicate sends. `sending_policy.py` is only a dry-run specification of some gates, not a production sender.
8. **Scheduled summary:** persistent scheduler generates an idempotent 5 PM Malaysia snapshot with reconciliation and synchronization coverage. Summary delivery, if wanted, needs separate approval and compliant messaging.

A free-form approved draft outside the allowed customer-service window cannot simply be sent unchanged: it must use an approved template with permitted variables and the appropriate category. Queue approval alone never enables automatic sending.

## Official requirements and number/device limits

Expect a Meta business portfolio, WhatsApp Business Account, business phone number, appropriate business verification/permissions, eligible display name, app/provider onboarding, phone-number and account identifiers, access credentials, secure HTTPS hosting, webhook subscriptions and message templates as applicable. Verification/review requirements depend on the chosen route and account. A provider may handle some of these steps; check its contracts, fees and data access.

**Coexistence eligibility is an onboarding decision, not something this CRM can guarantee.** The existing number must be an eligible WhatsApp Business app number; consumer WhatsApp and all existing Business setups should not be assumed eligible. Country, account, provider and supported onboarding flow can affect availability. The ordinary API-only migration route can change app usability, so do not approve migration when your requirement is to retain app use without first understanding the result.

With eligible Coexistence, supported Business app and Cloud API use can share a number. Web/Desktop and linked-device support must be verified for your actual onboarding route, client versions and account. App-sent message echo and optional history-sharing mechanisms may have restrictions; Web/Desktop is not an API feed and must not be scraped. Do not assume all old history, group chats, disappearing/view-once media, edits/deletes, linked-device activity or every message type will synchronize. The live CRM must display gaps rather than infer that an unseen reply never occurred. Test both directions: app/Desktop send → CRM event, API send → app visibility, replies → CRM event, and media/history coverage.

A customer message normally opens a 24-hour customer-service window for supported free-form replies. Outside that window, proactive messages generally require approved templates. Apply WhatsApp's current consent/opt-in, opt-out, quality, content and rate-limit rules; do not use consent as a one-time blanket license to message indefinitely. Categories and pricing treatment for sales follow-ups must be verified; a sales follow-up is not automatically an eligible utility template. Current account/API policies take precedence over this planning guide.

## Costs

No Meta or AI usage costs are incurred by this sample prototype. Production costs normally include:

- Meta charges for billable delivered template messages, depending on recipient market, template category, rate tiers and applicable free-message rules.
- Provider/BSP subscription, onboarding, per-message markup, seats or inbox fees if using a provider.
- AI usage by input/output volume; PDF extraction/OCR can add charges.
- HTTPS hosting, persistent disk, private backups, monitoring and maintenance.

Do not use a flat “RM per WhatsApp conversation” estimate. Budget as **billable template volume × applicable Meta rate + provider fees + AI usage + hosting**, converted to RM at the actual exchange rate/tax. The recipient's country matters; a Malaysian business may message customers in other countries. Request a written provider quote covering Coexistence, history/media coverage, Desktop behavior, markup, cancellation and taxes. No exact current RM quote or eligibility claim is made here.

Official reference pages to verify before connecting (retrieval was blocked by this environment's network policy, so live rules/rates were not independently checked):

- [Meta: onboarding WhatsApp Business app users / Coexistence](https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users/)
- [Meta: Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/)
- [Meta: webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
- [WhatsApp: platform pricing](https://business.whatsapp.com/products/platform-pricing)
- [WhatsApp: business messaging policy](https://business.whatsapp.com/policy)

## Implementation stages and your next steps

**Stage 1 — completed here:** preserve CRM; sample conversations; conservative analysis; multilingual drafts; approval queue; local 5 PM summaries; regression and safety tests. No connection or sending.

**Stage 2 — official sandbox:** add webhook verification, durable event ingestion and media parsing using Meta's test number or provider sandbox. Test duplicates, out-of-order events, statuses, signature failures, consent, templates, AI accuracy and identity matching. No real-number connection without your explicit approval.

**Stage 3 — approved Coexistence pilot:** verify eligibility and costs with your chosen official provider, back up the CRM, then obtain your approval before onboarding the real number. Begin with inbound analysis and approval-only drafts. Test app/Web/Desktop behavior and incomplete history openly with a small consenting test group.

**Stage 4 — controlled sending:** only after separate approval and successful testing, enable official API sending for approved drafts with immediate policy checks and audit logs. Automatic sends require an additional explicit enablement decision, opt-out handling, limits, template checks, duplicate protection and an emergency off switch. Do not enable them merely because a draft was approved.

For now:

1. Restart the CRM using your normal README command; your existing login still works.
2. Open Sales Assistant → Load sample conversations.
3. Review the examples, try all three languages, and approve/reject drafts. Nothing will be sent.
4. Start `summary_worker.py` if you want the local summary saved at 5 PM automatically.
5. For the next integration stage, tell us which official provider/onboarding route you prefer and whether your number is currently in the **WhatsApp Business app**. You do not need to share tokens, passwords or a QR code. Do not disconnect your existing WhatsApp account.
