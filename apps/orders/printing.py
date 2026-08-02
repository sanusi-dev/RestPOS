"""Print interface used by the POS until the printer agent is available."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintResult:
    """Result returned by a print attempt."""

    success: bool
    ticket_type: str


def print_ticket(ticket) -> PrintResult:
    """Simulate printing one ticket and return the stable printer interface result."""
    return PrintResult(success=True, ticket_type=ticket.ticket_type)


def print_receipt(order) -> PrintResult:
    """Simulate printing a customer receipt and return the stable printer interface result."""
    return PrintResult(success=True, ticket_type="receipt")
