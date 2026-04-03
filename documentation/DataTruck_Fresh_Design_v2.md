# DataTruck Support Agent — Fresh Design (v2)

## Thinking From First Principles

Forget the old system entirely. Let's start with one question:

**How does an excellent human support agent work in a Telegram group?**

They don't run a "classification pipeline." They do this:

1. They **read the room** — who's talking, what's the mood, what's been discussed recently, are there open issues
2. They **recognize patterns** — "oh, this is the same GPS problem three clients had last month"
3. They **remember what worked** — "last time someone had this, I told them to clear cache and it fixed it"
4. They **know when they don't know** — "this is new, I need to ask the team"
5. They **get better every day** — each resolved ticket teaches them something new

The old system did none of this. It classified each message in isolation, ran it through a rigid pipeline, and made the same mistakes over and over because it never learned from them.

**This design builds an agent that thinks, remembers, and improves.**

---

## 1. What Real Conversations Actually Look Like

I analyzed all 4 conversation exports (479 messages across Artel Logistics, Mir Transportation, KGStar, and UGL groups). This fundamentally changed the design.

### The Reality: Most Messages Are NOT Answerable From Documentation

| Pattern | Count | % | What The Bot Should Do |
|---|---|---|---|
| Greetings ("Assalomu alaikum", "hello team") | 51 | 10.6% | **Ignore** — no action needed |
| Call/meeting requests ("pls call me", "can we do a call") | 36 | 7.5% | **Escalate immediately** — bot can't make calls |
| Live Support redirects (agent posts standard message) | 39 | 8.1% | **Not needed anymore** — the bot makes Telegram groups work, so agents don't need to redirect users elsewhere |
| Screenshots (error screens, UI problems) | 53 | 11.0% | **Analyze + triage** — some answerable, most need human |
| Thank you / confirmation | 21 | 4.4% | **Ignore** — route to existing ticket silently |
| Urgent escalations ("urgent!", "asap") | 14 | 2.9% | **Escalate with HIGH priority** |
| @mention support agents | 23 | 4.8% | **Stay silent** — user wants that specific person, not a bot. Route to Zendesk silently. |
| Account-specific actions ("add driver", "remove company") | 9 | 1.9% | **Escalate** — requires human action in system |
| Actual answerable-from-docs questions | ~30 | ~6% | **Answer from documentation** |
| Internal coordination, follow-ups, noise | ~200 | ~42% | **Route to ticket silently** or **ignore** |

### Key Insights From Real Data

**1. The bot's #1 job is TRIAGE, not answering.**
Only ~6% of messages are answerable from documentation. The bot's biggest value is routing everything to the right Zendesk ticket, recognizing urgency, and escalating fast. Answering from docs is a bonus, not the core.

**2. Languages mix mid-sentence.**
"data truckni" (DataTruck + Uzbek suffix), "Siz aytgan narsalar payshanba chiqadi" (mixed Uzbek with Russian-style grammar). The bot must handle Uzbek/Russian/English seamlessly, often in the same message.

**3. "Please call me" is the #1 support pattern.**
36 out of 479 messages are requests for phone calls. The bot should immediately escalate these and notify a human agent — not try to answer by text.

**4. Screenshots carry the actual question.**
Users send screenshots with minimal text like "?" or "nima bu?" (what is this?). The bot needs vision to understand the screenshot, then either answer or escalate.

**5. @Datatruck_support is a HUMAN agent, not the bot.**
`@Datatruck_support`, `@Xojiakbar_CS_DataTruck`, `@mr_mamur` — these are all human agents. When users tag any of them, the bot stays silent. The bot's own username is `@datatrucksupportbot`. The bot only responds when it has a grounded answer to a support question — it doesn't need to be tagged.

**6. The "redirect to Live Support" messages disappear.**
Those messages exist because agents can't handle Telegram AND Zendesk. Once the bot handles Telegram properly, agents focus on Zendesk tickets and clients get answers in Telegram. No more redirecting.

**7. Most "support" is account-specific action.**
"Add a driver", "remove this company", "fix this statement", "migrate deductions". These are actions, not questions. The bot must recognize these and escalate with clear context for the human agent.

### Design Implication: The Agent's Priority Order

1. **Triage and route** (every message → right Zendesk ticket, silently)
2. **Answer from docs/memory** when the question IS answerable (~6% initially, growing over time)
3. **Recognize urgency** ("urgent", "asap", repeated @mentions → high-priority Zendesk ticket)
4. **Stay silent** when it can't help — escalate to Zendesk for human agents
5. **Learn from resolved tickets** to increase the answerable percentage over time
6. **Never speak when a human agent was specifically requested** (@mention of agent → silent + Zendesk route)

The bot speaks only when it has a confident, grounded answer. Otherwise it works invisibly — routing, triaging, and learning.

---

## 2. Four Types of Memory (The Brain)

Borrowing from cognitive science, the agent needs four distinct memory systems:

### Working Memory — "What's happening right now"
The current conversation in this Telegram group. Who said what, what the bot already replied, which tickets are open, what follow-up questions are pending.

**Stored in:** LangGraph checkpointer (per-group thread, persisted to PostgreSQL)
**Lifetime:** Active session. Automatically loaded when a message arrives.

### Semantic Memory — "What I know"
Facts about DataTruck's product: documentation, feature descriptions, how-to guides. Plus learned Q&A pairs from resolved tickets.

**Stored in:** Qdrant vector database (two collections: `docs` for Zendesk articles, `learned` for resolved Q&A pairs)
**Lifetime:** Permanent. Grows as documentation is updated and tickets are resolved.
**How it improves:** Every resolved ticket adds a new Q&A pair. Documentation auto-syncs from Zendesk.

### Episodic Memory — "What happened before"
Records of past conversations: "When User X asked about GPS sync, the bot tried answer A but user said it didn't work, then human agent provided answer B which worked." These are full interaction trajectories, not just Q&A pairs.

**Stored in:** LangGraph Store (PostgreSQL-backed, cross-thread, namespaced by topic)
**Lifetime:** Long-term. Decays over time (older episodes get lower retrieval priority).
**How it improves:** Every completed support conversation becomes a new episode. The agent can look up "what happened last time someone had this problem" and use it as a few-shot example.

### Procedural Memory — "How I should behave"
The agent's decision-making rules and prompts. Unlike the old system where prompts were hardcoded, procedural memory **evolves**:
- Few-shot examples in prompts are dynamically retrieved from real past interactions
- Decision rules can be updated based on patterns of success and failure
- The system prompt itself can be refined based on feedback

**Stored in:** LangGraph Store (PostgreSQL-backed, namespace: `procedural`)
**Lifetime:** Permanent, but versioned. Updated periodically as the system learns.
**How it improves:** After every N resolved tickets, a background process reviews recent successes/failures and refines the decision examples.

---

## 3. The Agent Architecture

### Framework: LangGraph 1.0

LangGraph is chosen because it natively supports all four memory types:
- **Working memory** → thread-scoped checkpointer
- **Semantic/Episodic/Procedural** → cross-thread Store
- **Decision logic** → graph nodes with conditional edges
- **Learning loops** → background nodes that update memory after ticket resolution

### The Graph

```
Message arrives
      │
      ▼
┌──────────┐     ┌──────────────────────────┐
│ perceive │────▶│ Working memory loaded     │
│          │     │ Relevant episodes fetched │
│          │     │ Relevant knowledge fetched│
│          │     │ Decision examples loaded  │
└────┬─────┘     └──────────────────────────┘
     │
     ▼
┌──────────┐
│  think   │  One LLM call with complete context:
│          │  "What is this message? What should I do?
│          │   Which ticket does it belong to?"
└────┬─────┘
     │
     ├──────────────┬──────────────┬──────────────┐
     ▼              ▼              ▼              ▼
  IGNORE         ANSWER         WAIT          ESCALATE
     │              │              │              │
     │              ▼              │              │
     │         ┌────────┐         │              │
     │         │retrieve│         │              │
     │         │ (RAG)  │         │              │
     │         └───┬────┘         │              │
     │             │              │              │
     │             ▼              │              │
     │         ┌────────┐         │              │
     │         │generate│         │              │
     │         │ answer │         │              │
     │         └───┬────┘         │              │
     │             │              │              │
     │        ┌────┴───┐          │              │
     │        ▼        ▼          │              │
     │     ANSWER   ESCALATE──────┼──────────────┤
     │        │                   │              │
     │        ▼                   │              ▼
     │     ┌──────┐         ┌─────────┐   ┌──────────┐
     │     │reply │         │ note    │   │ sync to  │
     │     │in TG │         │ waiting │   │ Zendesk  │
     │     └──┬───┘         └────┬────┘   │(+urgency)│
     │        │                  │        └────┬─────┘
     └────────┴──────────────────┴─────────────┘
                          │
                          ▼
                    ┌──────────┐
                    │ remember │  Update working memory
                    │          │  Sync message to Zendesk
                    │          │  Record interaction
                    └──────────┘


When a Zendesk ticket is SOLVED (webhook):
                    ┌──────────┐
                    │ learn    │  Extract Q&A → semantic memory
                    │          │  Save full trajectory → episodic memory
                    │          │  Update decision examples if needed
                    └──────────┘
```

### Node Descriptions

#### `perceive` — Build the agent's context window

No LLM call. Pure data assembly:

1. **Preprocess** the message (download photos, transcribe voice via Gemini Flash)
2. Load **working memory** from checkpointer (conversation history, active tickets, recently solved tickets)
3. Query **episodic memory**: "Have I seen a conversation like this before?" (semantic search on the message text, returns 1-2 most relevant past episodes)
4. Load **procedural memory**: Fetch the current decision prompt + dynamically selected few-shot examples relevant to this message type

No RAG probe here — retrieval only happens in the `retrieve` node after `think` decides `action="answer"`. This avoids wasting embedding API calls on greetings, thanks, call requests, and other non-answerable messages.

The agent now has its full context window assembled.

#### `think` — One decision, complete context

One LLM call (Claude Haiku) that receives:
- The current message + images
- Working memory (conversation history, active tickets, recently solved tickets, what the bot said last)
- Relevant past episodes ("last time someone said something like this, here's what happened")
- Dynamically selected few-shot examples from real past decisions

Returns a unified decision:
```json
{
  "action": "answer | ignore | wait | escalate",
  "urgency": "normal | high | critical",
  "ticket_routing": "existing:<id> | new | skip | followup:<source_id>",
  "extracted_question": "...",
  "language": "en | ru | uz",
  "reasoning": "..."
}
```

**The `urgency` field** handles the "its urgent!", "asap", repeated @mentions pattern. Critical urgency messages get flagged in Zendesk for immediate human attention.

**@mention of human agents** — when a user tags a specific person (like @Xojiakbar_CS_DataTruck), the bot stays completely silent in Telegram but still routes the message to Zendesk. The user asked for THAT person, not a bot.

**Why this is better than the old system**: The old system made 3 separate LLM calls (classifier, extractor, thread router) with different context. They could contradict each other. This is ONE call with EVERYTHING visible. And it includes real past examples of correct decisions, not hardcoded rules.

#### `retrieve` — Find the answer

Search Qdrant for relevant documentation and learned Q&A pairs. Uses the extracted question from `think`.

Two collections:
- `docs` — Zendesk Help Center articles (text + screenshots, multimodal embeddings via Gemini Embedding 2)
- `learned` — Resolved Q&A pairs from past tickets + historical conversations

Also downloads recent images from the user via Telegram `file_id` (stored in DB). If the user sent 3 screenshots then typed a question, the retrieve node fetches those actual images so `generate` can see them.

#### `generate` — Produce the answer

One LLM call (Claude Sonnet Vision) that generates the response from retrieved docs, learned answers, and actual screenshots. If the user sent photos, Sonnet sees both the documentation AND the screenshots — producing contextual answers like "I can see Error 500 on your Loads page." If it can't produce a grounded answer, it returns `needs_escalation = true`.

#### `respond` — Send the Telegram reply

Builds the response text (answer + follow-up question if both exist), sends to Telegram, and saves two things to state: the composed text (`bot_response_text`) and the Telegram message_id (`bot_response_message_id`). These are used by `remember` to sync the exact same text to Zendesk and save the bot message to DB.

#### `remember` — Update all memories + log decision

After every message (all paths: ignore, answer, wait, escalate):
1. Sync user's message to Zendesk (create/route/comment on ticket)
2. Sync bot's response to Zendesk (using `bot_response_text` — same text user sees in Telegram)
3. Save `file_description` from `think` to the message row (so future conversation_history shows meaningful descriptions for photos/documents instead of empty text)
4. Save bot's response to DB with correct `bot_response_message_id` (so perceive sees it in conversation_history next time)
5. Log decision to `bot_decisions` table (action, reasoning, timing, answer text) — powers the admin dashboard's Performance and Decision Review pages

#### `learn` — Extract knowledge from resolved tickets (triggered by webhook)

When a Zendesk ticket is solved:
1. **Semantic learning**: Summarize the Q&A pair → embed → store in Qdrant `learned` collection
2. **Episodic learning**: Save the full conversation trajectory (question → bot attempt → user feedback → human resolution) → store in LangGraph Store
3. **Procedural learning**: If this resolution reveals a pattern (e.g., "GPS questions always need escalation"), flag it for prompt example update

### How Different Message Types Are Handled

Every message type (text, photo, voice, document) flows through the same graph, but each is handled differently:

**Text messages**: `text` = user's typed text. Straightforward — think sees the text, decides action.

**Photos/documents (with caption)**: `text` = caption, `file_id` = Telegram reference to the file. Think sees the caption + actual image via Vision. Think ALWAYS produces a `file_description` (e.g., "Screenshot of Loads page with Error 500") even when caption exists — because the caption "How to fix this?" doesn't describe what's in the image.

**Photos/documents (without caption)**: `text` = "" (empty), `file_id` = Telegram reference. Think analyzes the image via Vision and produces `file_description`. Without this description, future conversation history would show the message as blank.

**Photo sent as file** (user sends image as document): treated the same as a regular photo. `file_type` = "photo" (detected by image/* mime type). `file_description` always generated.

**Voice messages**: Preprocessor transcribes via Gemini Flash → `text` = transcription. No `file_description` needed because the meaning is already in the text.

**How conversation history represents each type** (what think sees for past messages):

```
Adam: How do I change load status?                    ← text
Adam: [Photo: Screenshot of Loads page with Error 500] ← photo without caption
Adam: [Photo: Settings page] How do I fix this?        ← photo with caption
Adam: [Voice] load statusni qanday o'zgartiraman?      ← voice, transcribed
Adam: [File: PDF invoice for March] Check this          ← document with caption
Bot: To change load status, go to Settings...           ← bot response
```

**Image handling approach (Approach 3 — hybrid):**

When a user sends photos and then asks a text question about them:

1. **Photo arrives** → think (Haiku Vision, cheap) describes it → `file_description` saved to DB
2. **Text question arrives** → perceive loads file_descriptions in conversation_history → think sees "Adam sent screenshots of Error 500, now asks about errors" → enriches `extracted_question`
3. **retrieve** downloads actual images via `file_id` from recent messages
4. **generate** (Sonnet Vision, expensive) sees documentation + actual screenshots → contextual answer

Cheap model for understanding, expensive model only when answering. `file_id` stored permanently for future use.

---

## 4. Self-Improvement: How The System Gets Smarter

### Loop 1: Every Resolved Ticket → New Knowledge

```
User asks question
  → Bot can't answer → escalates to Zendesk
  → Human agent answers
  → Ticket solved
  → learn node fires:
      1. Q: "How to fix GPS sync?" A: "Go to Settings > GPS > Reset token"
         → embedded and stored in Qdrant `learned` collection
      2. Full trajectory saved as episode
  → Next time someone asks about GPS sync:
      retrieve node finds the learned answer
      → Bot answers without escalation
```

**This is how the bot gets smarter with every ticket.**

### Loop 2: Historical Conversations → Bootstrap Knowledge

You said you have a lot of past conversations. Here's how to use them:

```python
# scripts/learn_from_history.py
# Run ONCE to bootstrap the system from historical data

async def bootstrap_from_conversations(conversations: list[dict]):
    """Process historical Telegram/Zendesk conversations to build initial memory."""

    for conv in conversations:
        # 1. Extract Q&A pairs → semantic memory
        qa_pairs = await extract_qa_pairs(conv)  # LLM call to identify question-answer pairs
        for qa in qa_pairs:
            await qdrant.upsert("learned", embed(qa.question), {
                "question": qa.question,
                "answer": qa.answer,
                "source": "historical",
                "confidence": 0.8,  # lower than live-resolved tickets
            })

        # 2. Save full trajectories → episodic memory
        episode = await summarize_episode(conv)  # LLM summarizes the interaction pattern
        await store.put(
            namespace=("episodes", episode.topic_category),
            key=episode.id,
            value=episode.dict(),
        )

        # 3. Extract successful decision examples → procedural memory
        examples = await extract_decision_examples(conv)
        for ex in examples:
            await store.put(
                namespace=("procedural", "decision_examples"),
                key=ex.id,
                value=ex.dict(),
            )
```

After running this script, the bot starts with knowledge from ALL your past conversations — not just documentation. It knows:
- What questions clients actually ask (not what you think they ask)
- What answers actually worked (not what documentation says should work)
- What patterns lead to escalation (so it can escalate faster)

### Loop 3: Dynamic Few-Shot Examples → Better Decisions Over Time

The old system had **hardcoded examples** in the classifier prompt:
```
Message: "Good morning everyone!" → NON_SUPPORT
Message: "I have more questions" → CLARIFICATION_NEEDED
```

The new system has **dynamically retrieved examples from real interactions**:

```python
async def load_decision_examples(message_text: str) -> list[dict]:
    """Retrieve the most relevant past decision examples for this message."""
    # Search procedural memory for similar past decisions
    results = await store.search(
        namespace=("procedural", "decision_examples"),
        query=message_text,
        limit=5,
    )
    return [r.value for r in results]
```

These examples come from REAL conversations where the system made the right decision (confirmed by ticket resolution). As more tickets are resolved, the pool of examples grows, and the retrieved examples become more relevant to each new message.

**This means the prompts themselves improve over time, without you changing any code.**

### Loop 4: Failure Pattern Detection → Automatic Gap Identification

A background process (runs daily/weekly) analyzes recent escalations:

```python
async def analyze_escalation_patterns():
    """Find patterns in what the bot can't answer → identify documentation gaps."""
    recent_escalations = await get_escalations(last_n_days=7)

    # Group by topic similarity
    clusters = await cluster_by_topic(recent_escalations)

    for cluster in clusters:
        if cluster.count >= 3:  # Same topic escalated 3+ times
            report = {
                "topic": cluster.summary,
                "count": cluster.count,
                "example_questions": cluster.questions[:5],
                "recommendation": "Add documentation or approved answer for this topic",
            }
            await notify_admin(report)  # Post to admin dashboard / Slack
```

This tells you: "The bot was asked about 'bulk load import' 7 times this week and escalated every time. You should add documentation for this."

### Loop 5: Conversation Quality Feedback

When a human agent answers a ticket that the bot previously attempted to answer (but failed), the `learn` node compares:
- What the bot said vs. what the human agent said
- If they're different, the human's answer is stored with higher confidence
- The bot's failed attempt is recorded as a negative episodic example

Over time, this creates a quality signal: the bot learns not just what to say, but what NOT to say.

### Knowledge Import Methods (Admin Dashboard)

Three ways to feed knowledge into the system, each for a different use case:

**Quick Add Q&A** — simple form: type question, type answer, select language, save. Goes directly to Qdrant memory. Use when you spot a good Q&A while reading tickets. Takes 30 seconds per entry.

**Import from Zendesk API** — enter ticket IDs or date range. Dashboard fetches conversations directly from Zendesk API, Haiku extracts Q&A pairs, you review each pair (approve/edit/reject) before saving. Best for bulk importing historical solved tickets — no manual export needed.

**Upload conversation file** — drag & drop PDF/DOC of a conversation from non-Zendesk sources. Haiku extracts Q&A pairs, same review screen. For email, WhatsApp, or other channels.

All three converge to the same quality gate: extracted Q&A pairs are shown on a **review screen** where you approve, edit, or reject each pair before it enters memory. AI extracts, you curate.

---

## 5. Group Isolation: Same User, Different Groups

Each Telegram group represents a **different client/company** (Artel Logistics, Mir Transportation, KGStar, UGL, etc.). The same user may appear in multiple groups. Conversations must NEVER mix between groups.

### What is ISOLATED per group (never shared)

| Data | Isolation Key | Why |
|---|---|---|
| Working memory (conversation history) | `thread_id = group_id` | LangGraph checkpointer isolates per thread automatically. User A's conversation in Group 1 is invisible in Group 2. |
| Active tickets | `group_id` | The `think` node loads active tickets **for this group only**. User A may have ticket #100 in Group 1 and ticket #200 in Group 2 — completely separate. |
| User's current ticket | `(group_id, user_id)` | "Does this user have an open ticket?" is always scoped to the current group. |
| Conversation threads (DB) | `(group_id, user_id, zendesk_ticket_id)` | Each thread belongs to one group. |
| Bot's last response to user | `(group_id, user_id)` | What the bot said to User A in Group 1 is not visible when processing User A's message in Group 2. |
| Recently solved tickets | `group_id` | Solved tickets in Group 1 don't affect follow-up detection in Group 2. |

### What is SHARED across all groups (product knowledge)

| Data | Why Shared |
|---|---|
| Documentation (Qdrant `docs`) | DataTruck is the same product for all clients. |
| Learned Q&A (Qdrant `learned`) | If a resolved ticket taught the bot how to fix GPS sync, that answer helps ALL groups. |
| Episodic memory (past trajectories) | A successful resolution pattern in Group 1 helps the bot decide better in Group 2. |
| Procedural memory (decision examples) | How to classify and route messages is universal. |

### Concrete example — same user, two groups

```
Group 1 (Artel Logistics):
  User A: "My load is stuck in pending" → ticket #100 created
  Bot: "To change load status, go to..."
  User A: "thanks"

Group 2 (Mir Transportation):
  User A: "My load is stuck in pending" → ticket #200 created (SEPARATE ticket)
  Bot: "To change load status, go to..."  (same answer — from shared docs)
  User A: "that didn't work"
  → Escalates on ticket #200 (NOT ticket #100)
```

Group 2's working memory has zero knowledge of what happened in Group 1. But the bot's ability to answer "load stuck in pending" comes from shared documentation — which is correct because it's the same product.

### How the `perceive` node enforces isolation

```python
async def perceive(state: SupportState) -> dict:
    group_id = state["group_id"]
    user_id = state["sender_id"]

    # ISOLATED: load only this group's data
    conversation_history = await db.get_recent_messages(group_id=group_id)
    active_tickets = await db.get_active_tickets(group_id=group_id)
    user_ticket = await db.get_user_active_ticket(
        group_id=group_id, user_id=user_id
    )
    recently_solved = await db.get_recently_solved_threads(group_id=group_id)
    bot_last = await db.get_bot_last_response(
        group_id=group_id, user_id=user_id
    )

    # SHARED: search across all groups (product knowledge)
    episodes = await episodic_store.search(query=state["raw_text"])
    decision_examples = await procedural_store.search(query=state["raw_text"])
    # NO RAG probe here — retrieval only in retrieve node after think decides

    return {
        "conversation_history": conversation_history,
        "active_tickets": active_tickets,
        "user_active_ticket": user_ticket,
        "recently_solved_tickets": recently_solved,
        "bot_last_response": bot_last,
        ...
    }
```

Every DB query that touches conversation data includes `group_id` as a filter. Every search against shared knowledge does NOT filter by group — because product knowledge is universal.

### Database indexes that enforce isolation

```sql
-- Conversation history: always filtered by chat_id
CREATE INDEX idx_msg_chat_created ON messages(chat_id, created_at);
-- Bot's last response: filtered by chat_id + source
CREATE INDEX idx_msg_chat_source_created ON messages(chat_id, source, created_at);
-- Active threads: filtered by group_id
CREATE INDEX idx_thread_group_status ON conversation_threads(group_id, status);
-- User's active thread: filtered by group_id + user_id
CREATE INDEX idx_thread_group_user_status ON conversation_threads(group_id, user_id, status);
-- Dedup: no duplicate messages
CREATE UNIQUE INDEX uq_chat_message ON messages(chat_id, message_id);
```

All queries go through these indexes — it's structurally impossible to accidentally load another group's data.

---

## 6. How Real Scenarios Are Handled (From Your Conversations)

### Scenario A: "pls call me, its about statements" (Mir Transportation)

Real message: `Sardorbek: can someone call us pls, its about statements`

```
perceive: text = "can someone call us pls, its about statements"
  episodic memory: finds past episode where call requests → agent called back
  working memory: active ticket #301 about statements for this group

think (one Haiku call):
  → action: escalate (bot can't make phone calls — needs human)
  → urgency: high (explicit request for immediate attention)
  → ticket_routing: existing:301 (about statements, active ticket exists)
  → reasoning: "User requests phone call about ongoing statements issue.
     Bot cannot make calls. Escalate with high urgency for human agent."

remember (Zendesk sync):
  1. Post user's message as comment on ticket #301, set high urgency
  2. No bot comment (escalation — human agent calls back)
  (bot stays SILENT in Telegram)
```

### Scenario B: Screenshot with "?" (KGStar)

Real message: `Rick: [screenshot] hello team, can you please explain this "Vendor" button?`

```
perceive: text = "hello team, can you explain this Vendor button?"
  image = [screenshot of UI]
  working memory: no active ticket for Rick in this group

think:
  → action: answer (question about UI feature, docs have relevant content)
  → ticket_routing: new (no active ticket for this user)
  → extracted_question: "What is the Vendor button/section in DataTruck?"

retrieve: finds Vendor management documentation
generate: produces answer explaining Vendor feature from docs
respond: sends answer in Telegram

remember (Zendesk sync — always question first, then answer):
  1. Create Zendesk ticket
     subject: "What is the Vendor button?"
     body: user's original message + screenshot attachment
     requester: Rick's Zendesk profile
  2. Post bot's answer as a second comment on the same ticket
     author: bot's Zendesk user
  3. Update working memory — Rick now has active ticket
```

**Zendesk sync order (applies to all paths):**
- **answer path**: user's message creates/updates ticket → bot's answer posted as comment
- **escalate path**: user's message creates/updates ticket → no bot comment (human agent takes over)
- **ignore path**: user's message posted to existing ticket if one exists (keeps Zendesk history complete)
- **wait path**: user's message posted to existing ticket if one exists

### Scenario C: "data truck ishlamay qoldi" — system outage (Mir Transportation)

Real message: `Аsalya: data truck ishlamay qoldi` (DataTruck stopped working)

```
perceive: text = "data truck ishlamay qoldi" (Uzbek: DataTruck stopped working)
  working memory: another user (Mike Morgan) just said "Web page ishlamay qoldi"

think:
  → action: escalate (system outage, multiple users reporting)
  → urgency: critical
  → ticket_routing: new (system-wide issue)
  → language: uz
  → reasoning: "System outage reported by multiple users. Cannot resolve from docs."

remember (Zendesk sync):
  1. Create ticket with CRITICAL priority
     subject: "System outage — multiple users reporting"
     body: user's message, tags: ["outage", "multiple_users"]
  2. No bot comment (escalation — human agents handle outage)
  (bot stays SILENT in Telegram)
```

### Scenario D: "add a driver to datatruck" (UGL)

Real message: `Muzaffar: Need to add a driver to the datatruck pls`

```
think:
  → action: escalate (account action — requires admin access in the system)
  → urgency: normal
  → ticket_routing: new
  → reasoning: "Adding a driver requires admin access. Bot cannot do this."

remember (Zendesk sync):
  1. Create ticket — subject: "Add driver request"
     body: user's original message
     requester: Muzaffar's Zendesk profile
  2. No bot comment (escalation — human agent handles the action)
  (bot stays SILENT in Telegram)
```

### Scenario E: "fixed it, thanks" after receiving help (Artel)

Real message: `Adam: tushunarli, rahmat` (understood, thanks) after agent explained something

```
think:
  → action: ignore
  → ticket_routing: existing:456 (user's active ticket about load status)

remember (Zendesk sync):
  1. Post "tushunarli, rahmat" as comment on ticket #456
     (keeps Zendesk history complete — human agents see the user confirmed)
  2. No bot comment (nothing to say)
  (no Telegram reply — bot stays silent on thank-you messages)
```

---

## 7. Tech Stack

### Core
| Component | Choice | Role |
|---|---|---|
| **Orchestration** | **LangGraph 1.0+** | Graph-based agent with checkpointing, conditional edges, background tasks |
| **Working memory** | **`langgraph-checkpoint-postgres` 3.x** | Per-group conversation state, auto-persisted |
| **Long-term memory** | **`AsyncPostgresStore`** (LangGraph built-in) | Episodic memory, procedural memory (cross-thread) |
| **Semantic memory** | **Qdrant** | Documentation + learned Q&A pairs (vector search) |
| **Embeddings** | **Gemini Embedding 2** (`gemini-embedding-2-preview`) | 3072-dim multimodal (text + images) |

### LLMs
| Task | Model | Cost |
|---|---|---|
| `think` node (decide + extract) | **Claude Haiku** | Fast, cheap. One call replaces three. |
| `generate` node (answer) | **Claude Sonnet** | Quality for user-facing responses |
| Voice transcription | **Gemini Flash** | Audio → text |
| `learn` node (summarize resolved tickets) | **Claude Haiku** | Background, not latency-sensitive |
| Bootstrap historical conversations | **Claude Haiku** | One-time batch processing |

### Infrastructure
| Component | Choice |
|---|---|
| Telegram bot | **aiogram 3.x** |
| Database | **PostgreSQL 16** (conversation data + LangGraph checkpoints + LangGraph Store) |
| ORM | **SQLAlchemy 2.0 (async)** + asyncpg |
| API server | **FastAPI + Uvicorn** (webhooks, health checks) |
| HTTP client | **httpx** (async, for Zendesk API) |
| Config | **pydantic-settings** |
| Logging | **loguru** |
| Retries | **tenacity** |
| Containers | **Docker Compose** |

---

## 8. Project Structure

```
src/
├── agent/                              # The intelligent agent
│   ├── graph.py                        # LangGraph StateGraph definition
│   ├── state.py                        # SupportState TypedDict
│   ├── nodes/
│   │   ├── perceive.py                 # Assemble context (all 4 memory types)
│   │   ├── think.py                    # Unified decision (Haiku)
│   │   ├── retrieve.py                 # RAG from docs + learned answers
│   │   ├── generate.py                 # Answer generation (Sonnet)
│   │   ├── respond.py                  # Send Telegram reply
│   │   ├── remember.py                 # Update working memory + sync Zendesk
│   │   └── learn.py                    # Extract knowledge from resolved tickets
│   ├── edges.py                        # Conditional routing functions
│   └── prompts/
│       ├── think_prompt.py             # Decision prompt (with dynamic examples)
│       └── generate_prompt.py          # Answer generation prompt
│
├── memory/                             # Memory subsystems
│   ├── working.py                      # Checkpointer setup + context loading
│   ├── semantic.py                     # Qdrant: docs + learned Q&A
│   ├── episodic.py                     # LangGraph Store: past episodes
│   └── procedural.py                   # LangGraph Store: decision examples + rules
│
├── learning/                           # Self-improvement
│   ├── ticket_learner.py              # Extract knowledge from resolved tickets
│   ├── episode_recorder.py            # Save full conversation trajectories
│   ├── example_selector.py            # Dynamic few-shot example retrieval
│   ├── gap_analyzer.py                # Detect documentation gaps from escalation patterns
│   └── history_bootstrapper.py        # Process historical conversations
│
├── zendesk/                            # Zendesk integration
│   ├── api_client.py                   # HTTP client for Support API
│   ├── webhook_handler.py              # Zendesk → Telegram delivery + learning trigger
│   ├── profile_service.py             # User identity resolution
│   ├── help_center.py                 # Help Center API (for doc ingestion)
│   └── schemas.py                      # Pydantic models
│
├── rag/                                # Retrieval
│   ├── retriever.py                    # Qdrant query (docs + learned)
│   ├── embedder.py                     # Gemini Embedding 2 wrapper
│   └── reranker.py                     # Score threshold filter
│
├── ingestion/                          # Documentation ingestion
│   ├── zendesk_fetcher.py
│   ├── chunker.py
│   ├── indexer.py
│   └── sync_manager.py
│
├── telegram/                           # Telegram I/O (thin)
│   ├── bot.py                          # aiogram setup
│   ├── handler.py                      # Message → graph.ainvoke()
│   ├── formatter.py                    # Markdown → MarkdownV2
│   └── preprocessor.py               # Voice/photo/doc download
│
├── database/                           # PostgreSQL
│   ├── engine.py
│   ├── models.py                       # Users, groups, messages, threads
│   └── queries.py
│
├── api/
│   └── app.py                          # FastAPI (webhooks, health, admin)
│
└── config/
    └── settings.py

scripts/
├── ingest_docs.py                      # Initial documentation ingestion
├── bootstrap_from_history.py           # Process historical conversations
├── analyze_gaps.py                     # Run escalation pattern analysis
└── update_examples.py                  # Refresh procedural memory examples
```

---

## 9. How Historical Conversations Feed The System

You said you have a lot of past conversations. Here's the concrete plan:

### Step 1: Export and Structure
Export your Telegram group message history and Zendesk ticket history. Format them as conversation threads:
```json
{
  "group": "ABC Logistics",
  "messages": [
    {"from": "user_123", "text": "GPS is not syncing", "time": "..."},
    {"from": "bot", "text": "Try clearing the cache...", "time": "..."},
    {"from": "user_123", "text": "Didn't work", "time": "..."},
    {"from": "agent_karina", "text": "Go to Settings > GPS > Reset token", "time": "..."},
    {"from": "user_123", "text": "That fixed it, thanks!", "time": "..."}
  ],
  "zendesk_ticket": {"id": 456, "status": "solved", "subject": "GPS sync issue"}
}
```

### Step 2: Run `bootstrap_from_history.py`
This script processes each conversation and extracts:

1. **Q&A pairs** → Qdrant `learned` collection
   - Q: "GPS is not syncing" → A: "Go to Settings > GPS > Reset token"
   - These are REAL answers that ACTUALLY worked, not documentation guesses

2. **Full episodes** → LangGraph Store
   - "User asked about GPS → bot suggested cache clear → didn't work → human said reset token → worked"
   - Next time someone asks about GPS, the agent sees this episode and skips the bad suggestion

3. **Decision examples** → LangGraph Store (procedural)
   - "User said 'Didn't work' after bot answer → correct action: ESCALATE, route to existing ticket"
   - "User said 'Thanks that fixed it' → correct action: IGNORE, route to existing ticket"
   - These become few-shot examples in the `think` prompt

### Step 3: The System Starts Smart

After bootstrapping, the agent already knows:
- What questions clients actually ask
- What answers actually work (vs. what documentation says)
- What patterns of messages mean "I need help" vs. "I'm fine"
- When to escalate immediately (patterns that never resolve from docs)

**It starts at the level of an experienced support agent, not a blank slate.**

### Step 4: Continuous Improvement

Every new resolved ticket feeds all three memory types. The agent gets better every day, automatically:
- Week 1: Answers 40% of questions from docs, escalates 60%
- Week 4: Answers 55% from docs + learned answers, escalates 45%
- Week 12: Answers 70%+, escalation rate keeps dropping
- Ongoing: Documentation gaps identified, new docs written, agent gets even better

---

## 10. Implementation Roadmap

### Phase 1: Fresh Start + Core Graph
- Fresh database schema (6 tables: messages, conversation_threads, bot_decisions, 3 identity)
- Infrastructure fixes (shared httpx client, cached Gemini, .dockerignore, non-root Docker)
- LangGraph graph with `perceive`, `think`, `remember` nodes
- PostgreSQL checkpointer for per-group state isolation
- aiogram integration (message → preprocess → save to DB → graph)
- Basic `think` prompt with hardcoded examples

### Phase 2: Zendesk Sync
- Full `remember` node with Zendesk ticket create/route/comment
- Zendesk sync order: user's question first, bot's response second
- `bot_response_text` flow: respond saves to state → remember posts to Zendesk
- File upload as Zendesk attachments
- `file_description` saved to DB by remember

### Phase 3: Answer Generation
- `retrieve` node with Qdrant search + image download via `file_id`
- `generate` node (Sonnet Vision) with docs + screenshots
- `respond` node with bot_response_message_id tracking
- Full flow: perceive → think → retrieve → generate → respond → remember

### Phase 4: Learning
- Zendesk webhook handler → `learn` node
- Resolved ticket → Q&A extraction → Qdrant `learned` collection
- Episode recording → LangGraph Store
- Dynamic few-shot example retrieval for `think` prompt

### Phase 5: Bootstrap + Self-Improvement
- `bootstrap_from_history.py` script for historical conversations
- Escalation pattern analyzer (gap detection)
- Procedural memory updates
- Quality feedback loop (compare bot vs. human answers)

### Phase 6: Admin Dashboard
- Decision logging (`bot_decisions` table with timing)
- 6 dashboard pages: Overview, Performance, Knowledge Base, Decision Review, Conversations, Groups
- Knowledge import: Quick Add Q&A, Import from Zendesk API, conversation file upload
- Review screen for approving/editing/rejecting extracted Q&A pairs
- Decision correction buttons → feed into procedural memory

---

## 11. Admin Dashboard and Decision Analytics

### bot_decisions Table

Every message processed by the graph is logged with: action, reasoning, timing (ms per node), extracted question, answer text (if any), retrieval confidence. This powers two dashboard pages:

**Performance page**: answer rate trends, escalation rate trends, top escalated questions (tells you what docs to write), top answered questions, response time breakdown per node.

**Decision Review page**: filterable log of every bot decision. Click a row to see full context — what think saw, why it decided what it did, what docs were retrieved, what answer was generated. Correction buttons let you mark wrong decisions. Wrong decisions feed into procedural memory as "this was wrong, this is what should have happened" — improving future decisions.

### Knowledge Base with Import

Five tabs for managing what the bot knows:
- **Documentation**: browse Qdrant docs, sync with Zendesk Help Center
- **Learned Q&A**: browse memory entries, search, delete incorrect ones
- **Quick Add**: manually type Q&A pairs (30 seconds each)
- **Import from Zendesk**: fetch solved tickets via API → AI extracts Q&A → review screen
- **Upload**: ingest documentation files + conversation files with AI extraction

The Zendesk import is the most powerful — hundreds of solved tickets are already in Zendesk. One click to import a batch, review the Q&A pairs, and the bot immediately knows new answers.

---

## 12. Key Metrics: Is The System Improving?

| Metric | What It Measures | Target Trend |
|---|---|---|
| **Escalation rate** | % of support messages that need human help | ↓ decreasing over time |
| **First-response accuracy** | % of bot answers that resolve the issue (no "didn't work") | ↑ increasing |
| **Repeat escalation** | Same question type escalated more than once | ↓ approaching zero |
| **Resolution time** | Time from question to answer (bot or human) | ↓ as bot handles more |
| **Knowledge coverage** | % of question types that have a learned answer | ↑ approaching 100% |
| **Learned answer usage** | % of answers coming from learned memory vs. docs | ↑ (shows learning is working) |

---

## 13. Why This Design Is Fundamentally Different

### 13.1 Honest About What The Bot Can Do (Day 1 vs Month 6)

From analyzing 479 real messages, the bot's realistic capability trajectory:

**Day 1 (docs only):**
- Answer ~6% of messages from Zendesk Help Center documentation
- Correctly route ~90% of messages to Zendesk (the `think` node with good examples)
- Redirect to Live Support when it recognizes call requests, account actions
- Stay silent on greetings, thanks, internal coordination

**Week 4 (after bootstrapping historical conversations):**
- Answer ~15-20% of messages (learned Q&A from past resolved tickets)
- Better routing accuracy because episodic memory shows "this pattern always needs escalation"
- Fewer false positives (dynamic few-shot examples from real past decisions)

**Month 3 (continuous learning active):**
- Answer ~30-40% of messages (growing learned knowledge base)
- Auto-detect common patterns: "statement issues" → specific resolution steps
- Recognize repeat issues across different client groups
- Documentation gap reports identifying what docs to write

**Month 6+ (mature system):**
- Answer ~50-60% of questions (realistic ceiling — many issues ARE account-specific)
- Human agents focus only on account actions, complex bugs, and new issues
- Bot handles all routine questions and triage

**The ~40% that will ALWAYS need humans:**
- Account-specific actions ("add a driver", "remove this company", "migrate deductions")
- Phone call / screen sharing requests
- System outages and bugs
- Data corrections ("this statement amount is wrong")
- Business-specific decisions ("should we use this trailer type?")

The bot's goal is not to replace human agents. It's to handle the routine 50-60% so humans can focus on the complex 40%.

### 13.2 Comparison Table

| Aspect | Old Approach | This Design |
|---|---|---|
| **Intelligence model** | Classification pipeline — categorize then process | **Cognitive agent** — perceive, think, act, remember, learn |
| **Memory** | In-memory deque + isolated DB queries | **Four memory types** working together: working, semantic, episodic, procedural |
| **Learning** | None — same mistakes repeated forever | **Continuous** — every resolved ticket makes the system smarter |
| **Prompts** | Hardcoded examples that never change | **Dynamic** — few-shot examples retrieved from real past decisions |
| **Historical data** | Ignored | **Bootstrap** — past conversations seed all memory types on day one |
| **Decision making** | 3 separate LLM calls that can contradict | **1 call** with complete context including past episodes |
| **Documentation gaps** | Discovered by users complaining | **Auto-detected** from escalation patterns |
| **Human knowledge** | Lost when agent leaves | **Captured** — every human answer becomes permanent system knowledge |
| **Improvement** | Manual — requires code changes | **Automatic** — happens with every resolved ticket |
