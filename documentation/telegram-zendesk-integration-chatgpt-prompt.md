You are modifying an EXISTING Python project.

Important:
- DO NOT rebuild or replace my existing AI/classification/question-extraction logic.
- My current project already reads Telegram messages, classifies them, extracts the support question, and has core app structure.
- Your job is ONLY to add the Telegram ↔ Zendesk integration layer and persistence around it.

==================================================
PROJECT GOAL
==================================================

Implement this architecture:

1) Telegram -> Backend -> Zendesk
2) Zendesk -> Webhook POST -> Backend -> Telegram

Behavior:
- Every Telegram group is independent and belongs to a different client/company.
- All Telegram messages must be stored in the database.
- When a Telegram user writes in a group, backend must:
  a) identify/create that Telegram user locally
  b) identify/create corresponding Zendesk user profile using Telegram unique user id as stable external key
  c) create or update Zendesk ticket/comment using that mapped Zendesk user as requester/author
- When a human agent writes inside Zendesk UI, backend must receive webhook and mirror that comment back to the correct Telegram group.
- Comments written by our backend via Zendesk API using the integration token MUST NOT be mirrored back to Telegram.
- I want to mirror BOTH public and private Zendesk comments to Telegram.
- Plain Telegram groups only. No forum topics / no message_thread_id support needed for now.

==================================================
EXISTING PROJECT CONSTRAINTS
==================================================

- Keep all existing Telegram message reading, classification, question extraction, and AI logic.
- Use extracted question from existing logic as Zendesk ticket subject for new tickets.
- Use my existing project patterns, config system, database stack, and coding style where possible.
- Add code incrementally and cleanly.
- Avoid unrelated refactors.

==================================================
HIGH-LEVEL DESIGN
==================================================

Implement these integration components:

A. Telegram inbound flow
- Receive Telegram webhook updates
- Store ALL Telegram updates and messages in DB
- Normalize user/group/message/attachment data
- Find or create Zendesk user/profile mapped to Telegram user
- Decide whether to create a new Zendesk ticket or append comment to existing ticket
- Send message/comment/attachment to Zendesk

B. Zendesk outbound flow
- Receive Zendesk webhook POST in backend
- Accept only comments written by human agents in Zendesk UI
- Reject/ignore comments created by our integration user/token
- Find mapped Telegram group for the Zendesk ticket
- Send mirrored message to Telegram
- Store mirrored outbound Telegram message in DB

C. Replay / reliability
- Add idempotency and deduplication for both Telegram and Zendesk webhooks
- Add robust logging
- Add optional reconciliation worker for Zendesk later, but implement hooks for it now

==================================================
NAMING / USER MAPPING RULES
==================================================

For Telegram user -> local display name:
- If first_name or last_name exists:
  - display_name = trimmed "first_name last_name"
- Else if username exists:
  - display_name = username
- Else:
  - display_name = "telegram_user_<telegram_user_id>"

Do NOT append Telegram group name to the Zendesk user profile name.
Reason:
- one person may appear in multiple groups
- the group belongs on ticket/group records, not person identity

For Zendesk profile mapping:
- stable external key = "telegram_<telegram_user_id>"
- save mapping in DB:
  - telegram_user_id
  - zendesk_user_id
  - zendesk_profile_id if available
  - zendesk_external_id

If user is not found locally:
1) check Zendesk by external_id/profile identifier
2) if found, store in DB
3) if not found, create it in Zendesk, then store in DB

==================================================
ZENDESK API USAGE RULES
==================================================

Use one dedicated Zendesk integration user/token for ALL backend API calls.

Use these APIs:

1) Zendesk Profiles / user mapping
- Find or create profile/user using Telegram external id
- Persist returned zendesk user id locally
- This user id will be used as requester_id and comment.author_id

2) Create ticket
- Use Zendesk Tickets API
- For first Telegram message creating a ticket:
  - subject = existing extracted question from current logic
  - requester_id = mapped zendesk user id
  - comment.author_id = same mapped zendesk user id
  - comment.body = formatted body from Telegram message content
  - tags must include "source_telegram"
  - custom_fields must include telegram chat id field with value = Telegram group chat id
  - optionally include telegram root message id custom field if available

3) Update ticket / append comment
- Use Zendesk ticket update API
- For subsequent Telegram messages appended to same ticket:
  - comment.author_id = mapped zendesk user id
  - comment.body = formatted body from Telegram content
  - keep tags/source_telegram intact
  - update useful custom fields if needed

4) Attachments
- If Telegram message includes file/photo/document:
  - download from Telegram
  - upload file to Zendesk uploads endpoint
  - include returned upload token in ticket comment.uploads
- If message is voice:
  - use existing project logic/transcription result as text comment body
  - if raw audio should also be attached and supported by current pipeline, upload it too
- If message is sticker:
  - create readable text fallback in comment body, e.g. "[Sticker received]"
  - attach sticker file only if current pipeline can obtain and upload it reliably

==================================================
TELEGRAM -> ZENDESK ROUTING RULES
==================================================

Ticket routing rules:
- If Telegram message is a reply to a Telegram message already linked to an OPEN Zendesk ticket:
  -> append comment to that ticket
- Else:
  -> create a NEW Zendesk ticket

For now:
- standalone new Telegram messages create new tickets
- replies to linked messages append to existing open tickets

Need local mapping table so backend can determine:
- which Telegram message belongs to which Zendesk ticket
- which Zendesk comment was created from which Telegram message

==================================================
ZENDESK -> TELEGRAM WEBHOOK RULES
==================================================

Implement backend endpoint(s) to receive Zendesk webhook POSTs.

Important requirement:
- Telegram should receive messages ONLY when comments are written by human agents in Zendesk UI
- Telegram should NOT receive messages for comments created by our backend through Zendesk API

Implement this by assuming Zendesk trigger configuration will exclude the dedicated integration user.
Still add backend safety checks and dedupe.

Expected webhook payload should include at minimum:
- zendesk ticket id
- current user id
- current user name
- latest comment text
- telegram chat id from Zendesk custom field
- maybe status if included

Mirror both private and public comments to Telegram because this is my current requirement.

Message format to Telegram:
- first line: [Ticket #<ticket_id>]
- second line: Agent: <agent_name>
- blank line
- comment body

If attachment info becomes available in webhook payload or via follow-up fetch:
- send media/file accordingly
- otherwise send text only

==================================================
DATABASE CHANGES
==================================================

Add or adapt tables/models to support this integration.

1) telegram_users
Fields:
- id
- telegram_user_id (unique)
- username nullable
- first_name nullable
- last_name nullable
- display_name
- zendesk_external_id nullable unique
- zendesk_user_id nullable
- zendesk_profile_id nullable
- created_at
- updated_at

2) telegram_groups
Fields:
- id
- telegram_chat_id (unique)
- title nullable
- company_key nullable
- zendesk_organization_id nullable
- zendesk_group_id nullable
- active boolean
- created_at
- updated_at

3) telegram_updates
Fields:
- id
- telegram_update_id (unique)
- raw_payload json/jsonb
- received_at
- processed_at nullable
- status
- error nullable

4) telegram_messages
Fields:
- id
- telegram_chat_id
- telegram_message_id
- telegram_reply_to_message_id nullable
- telegram_user_id nullable
- direction enum/inbound-outbound
- message_type
- text nullable
- caption nullable
- raw_payload json/jsonb
- sent_at
- created_at
- updated_at
- unique(chat_id, message_id)

5) telegram_attachments
Fields:
- id
- telegram_message_fk
- telegram_file_id nullable
- telegram_file_unique_id nullable
- telegram_file_path nullable
- original_file_name nullable
- mime_type nullable
- file_size nullable
- local_temp_path nullable
- zendesk_upload_token nullable
- zendesk_attachment_id nullable
- created_at

6) zendesk_users
Fields:
- id
- zendesk_user_id (unique)
- zendesk_profile_id nullable
- external_id unique
- name nullable
- role nullable
- created_at
- updated_at

7) zendesk_tickets
Fields:
- id
- zendesk_ticket_id (unique)
- requester_zendesk_user_id nullable
- zendesk_status nullable
- zendesk_group_id nullable
- zendesk_organization_id nullable
- subject nullable
- created_at
- updated_at

8) zendesk_comments
Fields:
- id
- zendesk_comment_id nullable unique
- zendesk_ticket_fk
- author_zendesk_user_id nullable
- author_name nullable
- body_text nullable
- public nullable
- source enum: telegram / zendesk_ui / zendesk_api / replay
- created_at
- mirrored_to_telegram_at nullable

9) message_links
Fields:
- id
- telegram_message_fk nullable
- zendesk_ticket_fk
- zendesk_comment_fk nullable
- link_type enum: root / reply / mirror
- created_at

10) zendesk_events
Fields:
- id
- dedupe_key unique
- raw_payload json/jsonb
- zendesk_ticket_id nullable
- current_user_id nullable
- current_user_name nullable
- processed boolean
- processing_error nullable
- received_at
- processed_at nullable

==================================================
BACKEND ENDPOINTS TO IMPLEMENT
==================================================

Implement or adapt these endpoints:

1) POST /telegram/webhook
Responsibilities:
- accept Telegram webhook
- store raw update
- enqueue/process normalized message
- return quickly

2) POST /api/zendesk/events
Responsibilities:
- accept Zendesk trigger-connected webhook
- authenticate / verify signature if configured
- store raw payload
- deduplicate
- mirror allowed comment to Telegram
- store outbound message/result

3) GET /health/live
4) GET /health/ready
5) GET /debug/ticket/{zendesk_ticket_id}
6) GET /debug/chat/{telegram_chat_id}

==================================================
INBOUND TELEGRAM PROCESSING STEPS
==================================================

For each Telegram update:

1) Store raw update in telegram_updates
2) Extract normalized message data
3) Upsert telegram_groups by chat_id
4) Upsert telegram_users by telegram_user_id
5) Store normalized message in telegram_messages
6) Resolve/create Zendesk user mapping:
   - check local DB first
   - if missing, check Zendesk by external_id
   - if not found, create profile/user in Zendesk
   - save mapping in DB
7) Determine routing:
   - if reply_to_message_id maps to linked open ticket => append comment
   - else => create new ticket
8) Build comment body from existing project output:
   - plain text if text message
   - caption + text if media with caption
   - transcript if voice
   - fallback markers for unsupported content
9) If attachment exists:
   - fetch/download from Telegram
   - upload to Zendesk
   - include upload token(s)
10) Call Zendesk create/update ticket API
11) Save zendesk_tickets / zendesk_comments / message_links records
12) Mark telegram_updates row processed

==================================================
OUTBOUND ZENDESK PROCESSING STEPS
==================================================

For each Zendesk webhook payload:

1) Store raw payload in zendesk_events
2) Build dedupe key and skip duplicates
3) Validate this event should be mirrored:
   - must belong to source_telegram ticket
   - must not originate from integration user
   - must contain a comment
4) Resolve mapped Telegram group:
   - primary source: local DB mapping by zendesk_ticket_id
   - fallback source: telegram chat id custom field from payload
5) Format Telegram message:
   [Ticket #<id>]
   Agent: <current_user_name>

   <latest_comment>
6) Send to Telegram group
7) Store outbound Telegram message in telegram_messages
8) Store zendesk_comments row if needed
9) Store message_links mirror row
10) Mark zendesk_events row processed

==================================================
ZENDESK TRIGGER / WEBHOOK ASSUMPTIONS
==================================================

Assume Zendesk side will be configured with:
- ticket tag contains source_telegram
- comment is present
- current user is agent
- current user is not the integration user

Also plan for separate webhook or processing path for:
- ticket status changed
- ticket closed / solved

These status events should update local DB ticket state.
Do NOT send status-only events to Telegram unless explicitly configured later.

==================================================
FILE / MEDIA HANDLING RULES
==================================================

Support these inbound Telegram types:
- text
- photo
- document
- voice
- audio
- video
- sticker

Handling:
- text -> comment body only
- photo/document/audio/video -> comment body + uploaded attachment if available
- voice -> transcript text required; attach audio too if current pipeline supports it
- sticker -> text fallback, attachment optional

Need clean helper/service layer for:
- Telegram file resolution/download
- Zendesk upload token creation
- comment upload attachment binding

==================================================
IDEMPOTENCY / LOOP PREVENTION
==================================================

Implement:
- Telegram dedupe by update_id and (chat_id, message_id)
- Zendesk dedupe by payload hash / event key
- never mirror integration-user API comments back to Telegram
- safe retries for network failures
- transaction boundaries so duplicate delivery does not create duplicate DB rows or duplicate ticket comments

==================================================
CODE ORGANIZATION
==================================================

Add or modify these areas only as needed:

- api/telegram_webhook.py
- api/zendesk_events.py
- services/telegram_service.py
- services/zendesk_service.py
- services/zendesk_profile_service.py
- services/attachment_service.py
- services/ticket_routing_service.py
- repositories/*
- models/*
- migrations/*
- workers/* if existing project already uses background workers

Keep code typed and production-style.
Prefer small methods, clear service boundaries, explicit error handling, and minimal coupling.

==================================================
WHAT TO DELIVER
==================================================

Modify my existing project to include:

1) DB migrations
2) DB models/entities
3) Telegram inbound integration flow
4) Zendesk user profile mapping flow
5) Zendesk ticket create/update flow
6) Telegram file -> Zendesk upload flow
7) Zendesk webhook receiver flow
8) Telegram mirror sender flow
9) loop prevention / dedupe
10) tests for core cases
11) docs/README update with env vars and setup steps

==================================================
ACCEPTANCE CRITERIA
==================================================

1) New Telegram user message in a group:
- user is stored locally
- Zendesk user/profile is found or created by Telegram external id
- new Zendesk ticket is created
- requester_id and author_id are that mapped Zendesk user

2) Reply in Telegram to previously linked message:
- comment is added to same open Zendesk ticket
- author_id is mapped Telegram user

3) Human agent replies in Zendesk UI:
- backend receives Zendesk webhook
- comment is mirrored to correct Telegram group
- mirrored Telegram message is stored in DB

4) Backend-created Zendesk comment using integration token:
- NOT mirrored back to Telegram

5) Telegram file/photo/document:
- saved/processed
- uploaded to Zendesk
- attached to ticket/comment

6) All Telegram messages are stored in DB
7) Duplicate deliveries do not create duplicates
8) Existing AI logic remains intact

==================================================
IMPLEMENTATION ORDER
==================================================

Do the work in this order:
1) inspect existing project structure and reuse patterns
2) add DB schema/migrations
3) implement Telegram user/group/message persistence
4) implement Zendesk profile mapping service
5) implement Zendesk ticket create/update service
6) implement file upload path
7) implement Zendesk webhook receiver
8) implement Telegram mirror sender
9) add tests
10) update docs

When making decisions, prefer correctness, idempotency, debuggability, and minimal change to the existing project.