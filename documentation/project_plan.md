Project: AI Agentic Support Bot for Telegram Client Groups

Goal
Build an AI-powered support system that can automatically assist clients in multiple Telegram groups using our internal documentation. The AI should reduce the workload of our human support team while ensuring accurate answers and proper escalation when needed.

Context
Our company communicates with clients through many Telegram groups. Each group contains discussions between clients and support staff. Due to the limited size of the support team, we cannot respond quickly to every question.

We want to build an AI support bot that can monitor these groups, understand client questions, and respond based on our internal documentation.

Key Requirements

1. Telegram Group Monitoring
- The system must connect to multiple Telegram groups.
- Each group must be handled independently.
- Conversations from different groups must never be mixed or used as context for each other.

2. Multilingual Support
Clients may ask questions in:
- English
- Russian
- Uzbek

The AI must:
- detect the language
- understand the question
- respond in the same language.

3. Conversation Understanding
Messages in Telegram groups often contain:
- greetings
- small talk
- multiple users talking
- partial or unclear questions

The AI must:
- analyze the conversation
- extract the actual support question
- ignore irrelevant parts (greetings, unrelated messages, etc.).

4. Documentation Knowledge Base (RAG)

Our documentation is hosted on a Zendesk Help Center at https://support.datatruck.io/hc/en-us.
It contains articles organized by categories and sections, with content in text and screenshot/image format.

The system must:

1. Fetch articles from the Zendesk Help Center API (categories, sections, articles with embedded images).
2. Process and chunk the documentation, preserving text-image relationships (screenshots often illustrate step-by-step instructions).
3. Convert text and images into multimodal embeddings using Google Gemini Embedding 2 (text and images embedded in the same vector space for cross-modal retrieval).
4. Store embeddings in a vector database (Qdrant).

The AI should use Retrieval-Augmented Generation (RAG) to answer questions strictly based on this documentation.

Requirements for the knowledge base:
- Must be easily updateable — periodic sync from Zendesk detects article changes and re-ingests automatically.
- Documentation changes should automatically update the vector database.
- Retrieval should prioritize the most relevant sections.
- Multimodal retrieval: a text question should be able to retrieve relevant screenshots alongside text content.

5. Answer Generation
When a valid question is extracted:

1. Retrieve relevant documents using vector search.
2. Generate a response grounded in the documentation.
3. Provide a clear and concise answer.

The AI must avoid hallucinating answers outside the documentation.

6. Escalation to Human Support

If the AI cannot find sufficient information in the documentation:

1. The system should create a support ticket via an API.
2. The ticket should include:
   - the extracted question
   - conversation context
   - group identifier
   - user information

3. The AI should reply to the client with a message like:
   "Your question has been forwarded to our support team. We will respond shortly."

4. The system should wait for a human support response and then send that response back to the Telegram group.

7. Ticket Workflow
- AI detects unanswerable question
- AI creates ticket via API
- Support team reviews
- Support team responds
- Response is automatically posted back to the Telegram group

8. System Architecture Expectations

The solution should include:

- Telegram Bot / Telegram API integration
- Message ingestion pipeline
- Question extraction module
- Language detection
- Multimodal RAG pipeline (text + image retrieval using Gemini Embedding 2)
- Vector database (Qdrant for multimodal embeddings)
- Zendesk Help Center ingestion pipeline (API-based article and image extraction)
- Ticketing system integration
- Group-level context isolation
- Logging and monitoring

9. Additional Considerations

- Prevent hallucinations.
- Ensure responses are grounded in documentation.
- Support high concurrency (many groups and users).
- Maintain conversation context within each group.
- System should be scalable and maintainable.

Desired Outcome

An AI agentic support bot capable of:
- monitoring Telegram groups
- understanding multilingual conversations
- extracting real support questions
- answering using documentation via multimodal RAG (text + screenshots from Zendesk, embedded with Gemini Embedding 2)
- escalating unknown issues to human support
- maintaining separate contexts for each Telegram group
- automatically staying in sync with the latest Zendesk help center content