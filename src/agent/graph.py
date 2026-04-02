"""Build the LangGraph support agent state machine."""

from __future__ import annotations

from functools import partial

from aiogram import Bot
from langgraph.graph import END, StateGraph

from src.agent.edges import route_after_generate, route_after_think
from src.agent.nodes.generate import generate_node
from src.agent.nodes.perceive import perceive_node
from src.agent.nodes.remember import remember_node
from src.agent.nodes.respond import respond_node
from src.agent.nodes.retrieve import retrieve_node
from src.agent.nodes.think import think_node
from src.agent.state import SupportState
from src.escalation.profile_service import ZendeskProfileService
from src.escalation.ticket_client import ZendeskTicketClient
from src.escalation.ticket_store import ConversationThreadStore
from src.learning.episode_recorder import EpisodeRecorder
from src.learning.example_selector import ExampleSelector


def build_graph(
    bot: Bot,
    zendesk_client: ZendeskTicketClient | None = None,
    profile_service: ZendeskProfileService | None = None,
    thread_store: ConversationThreadStore | None = None,
    bot_zendesk_user_id: int = 0,
    episode_recorder: EpisodeRecorder | None = None,
    example_selector: ExampleSelector | None = None,
) -> StateGraph:
    """Build and return the (uncompiled) support agent StateGraph.

    The `bot` instance is bound to the respond node via functools.partial
    so it can send Telegram messages. Zendesk services are bound to the
    remember node for bidirectional sync. Episodic and procedural memory
    services are bound to the perceive node.
    """
    graph = StateGraph(SupportState)

    # Add nodes
    graph.add_node(
        "perceive",
        partial(
            perceive_node,
            episode_recorder=episode_recorder,
            example_selector=example_selector,
        ),
    )
    graph.add_node("think", think_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("respond", partial(respond_node, bot=bot))
    graph.add_node(
        "remember",
        partial(
            remember_node,
            bot=bot,
            zendesk_client=zendesk_client,
            profile_service=profile_service,
            thread_store=thread_store,
            bot_zendesk_user_id=bot_zendesk_user_id,
        ),
    )

    # Entry point
    graph.set_entry_point("perceive")

    # perceive -> think (always)
    graph.add_edge("perceive", "think")

    # think -> conditional routing
    graph.add_conditional_edges(
        "think",
        route_after_think,
        {
            "answer": "retrieve",
            "ignore": "remember",
            "wait": "remember",
            "escalate": "remember",
        },
    )

    # retrieve -> generate (always)
    graph.add_edge("retrieve", "generate")

    # generate -> conditional: has answer or needs escalation?
    graph.add_conditional_edges(
        "generate",
        route_after_generate,
        {
            "respond": "respond",
            "escalate": "remember",
        },
    )

    # respond -> remember (always)
    graph.add_edge("respond", "remember")

    # remember -> END
    graph.add_edge("remember", END)

    return graph
