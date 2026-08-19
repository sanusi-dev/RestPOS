"""Daily P&L computation — preview and submit (no GL posting)."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounting.models import FiscalYear

from .models import (
    DRINKS,
    FOOD,
    DailyPnL,
    DailyPnLCogsRow,
    DailyPnLConsumptionRow,
    DailyPnLLine,
    PnLConfiguration,
    PnLRecurringExpense,
)
from .sources import (
    TWO,
    ZERO,
    business_day_window,
    cash_variance,
    drink_cogs,
    electricity,
    kitchen_consumption,
    orders_in_window,
    recurring_amount,
    round_off,
    sales_by_department,
)

THREE = Decimal("0.001")


def _pct(amount, gross):
    if not gross:
        return ZERO
    return ((amount / gross) * Decimal("100")).quantize(THREE)


def _split(amount, department):
    if department == FOOD:
        return amount, ZERO, amount
    if department == DRINKS:
        return ZERO, amount, amount
    return ZERO, ZERO, amount


@dataclass
class LineSpec:
    section: str
    label: str
    amount_food: Decimal = ZERO
    amount_drinks: Decimal = ZERO
    amount_total: Decimal = ZERO
    is_memo: bool = False
    source: str = DailyPnLLine.COMPUTED
    sort_order: int = 0
    percent_of_gross: Decimal = ZERO


@dataclass
class Computation:
    totals: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)
    cogs_rows: list = field(default_factory=list)
    consumption_rows: list = field(default_factory=list)


def _append(lines, spec):
    spec.sort_order = len(lines)
    lines.append(spec)


def compute_daily_pnl(pnl):
    """Build statement lines and totals from live sources plus the draft's inputs."""
    config = PnLConfiguration.load()
    start, end = business_day_window(pnl.business_date, config.business_day_start_hour)
    orders = orders_in_window(start, end)
    food, drinks = sales_by_department(orders)
    gross = (food + drinks).quantize(TWO)
    round_off_amount = round_off(orders)
    net = (gross + round_off_amount).quantize(TWO)
    cogs, cogs_rows = drink_cogs(start, end, orders)
    consumption, consumption_rows = kitchen_consumption(pnl.business_date)

    lines: list[LineSpec] = []
    _append(lines, LineSpec(DailyPnLLine.GROSS_SALES, "Gross sales", food, drinks, gross))
    _append(lines, LineSpec(DailyPnLLine.ROUND_OFF, "Round-off", ZERO, ZERO, round_off_amount))
    _append(lines, LineSpec(DailyPnLLine.NET_SALES, "Net sales", food, drinks, net))
    _append(lines, LineSpec(DailyPnLLine.COGS, "Cost of goods sold", ZERO, cogs, cogs))
    _append(
        lines,
        LineSpec(
            DailyPnLLine.KITCHEN_CONSUMPTION,
            "Kitchen consumption",
            consumption,
            ZERO,
            consumption,
            is_memo=True,
        ),
    )

    direct_food = direct_drinks = direct_total = ZERO
    elec = electricity(pnl, config.electricity_rate)
    if elec or pnl.electricity_opening is not None:
        _append(lines, LineSpec(DailyPnLLine.DIRECT, "Electricity", ZERO, ZERO, elec, source=DailyPnLLine.METER))
        direct_total += elec

    for row in pnl.material_qtys.select_related("material").all():
        if row.qty <= 0:
            continue
        amount = (row.qty * row.material.rate).quantize(TWO)
        _append(
            lines,
            LineSpec(DailyPnLLine.DIRECT, row.material.name, ZERO, ZERO, amount, source=DailyPnLLine.MATERIAL),
        )
        direct_total += amount

    employee_total = ZERO
    templates = list(PnLRecurringExpense.objects.filter(disabled=False))
    for expense in templates:
        amount = recurring_amount(expense, pnl.business_date, gross)
        food_amt, drinks_amt, total_amt = _split(amount, expense.department)
        if expense.kind == PnLRecurringExpense.DIRECT_DAILY:
            _append(
                lines,
                LineSpec(
                    DailyPnLLine.DIRECT, expense.name, food_amt, drinks_amt, total_amt, source=DailyPnLLine.SETTINGS
                ),
            )
            direct_food += food_amt
            direct_drinks += drinks_amt
            direct_total += total_amt

    for row in pnl.adhoc_rows.all():
        food_amt, drinks_amt, total_amt = _split(row.amount, row.department)
        if row.section == row.DIRECT:
            _append(
                lines,
                LineSpec(DailyPnLLine.DIRECT, row.label, food_amt, drinks_amt, total_amt, source=DailyPnLLine.ADHOC),
            )
            direct_food += food_amt
            direct_drinks += drinks_amt
            direct_total += total_amt

    gp_food = (food - direct_food).quantize(TWO)
    gp_drinks = (drinks - cogs - direct_drinks).quantize(TWO)
    gp = (net - cogs - direct_total).quantize(TWO)
    _append(lines, LineSpec(DailyPnLLine.GROSS_PROFIT, "Gross profit", gp_food, gp_drinks, gp))

    if pnl.employee_cost_override is not None:
        employee_total = pnl.employee_cost_override.quantize(TWO)
        _append(
            lines,
            LineSpec(DailyPnLLine.EMPLOYEE, "Employee costs", ZERO, ZERO, employee_total, source=DailyPnLLine.SETTINGS),
        )
    else:
        for expense in templates:
            if expense.kind not in {PnLRecurringExpense.EMPLOYEE_DAILY, PnLRecurringExpense.EMPLOYEE_MONTHLY}:
                continue
            amount = recurring_amount(expense, pnl.business_date, gross)
            food_amt, drinks_amt, total_amt = _split(amount, expense.department)
            _append(
                lines,
                LineSpec(
                    DailyPnLLine.EMPLOYEE, expense.name, food_amt, drinks_amt, total_amt, source=DailyPnLLine.SETTINGS
                ),
            )
            employee_total += total_amt

    prime = (cogs + employee_total).quantize(TWO)
    _append(lines, LineSpec(DailyPnLLine.PRIME_COST, "Prime cost", ZERO, cogs, prime, is_memo=True))

    depreciation = config.daily_depreciation.quantize(TWO)
    _append(
        lines,
        LineSpec(DailyPnLLine.DEPRECIATION, "Depreciation", ZERO, ZERO, depreciation, source=DailyPnLLine.SETTINGS),
    )
    variance = cash_variance(start, end, config.include_cash_variance)
    _append(
        lines,
        LineSpec(DailyPnLLine.CASH_VARIANCE, "Cash variance", ZERO, ZERO, variance, source=DailyPnLLine.VARIANCE),
    )

    indirect_total = employee_total + depreciation + variance
    for expense in templates:
        if expense.kind not in {
            PnLRecurringExpense.INDIRECT_DAILY,
            PnLRecurringExpense.INDIRECT_MONTHLY,
            PnLRecurringExpense.INDIRECT_PERCENT,
        }:
            continue
        amount = recurring_amount(expense, pnl.business_date, gross)
        food_amt, drinks_amt, total_amt = _split(amount, expense.department)
        _append(
            lines,
            LineSpec(
                DailyPnLLine.INDIRECT, expense.name, food_amt, drinks_amt, total_amt, source=DailyPnLLine.SETTINGS
            ),
        )
        indirect_total += total_amt
    for row in pnl.adhoc_rows.all():
        if row.section != row.INDIRECT:
            continue
        food_amt, drinks_amt, total_amt = _split(row.amount, row.department)
        _append(
            lines,
            LineSpec(DailyPnLLine.INDIRECT, row.label, food_amt, drinks_amt, total_amt, source=DailyPnLLine.ADHOC),
        )
        indirect_total += total_amt

    np = (gp - indirect_total).quantize(TWO)
    _append(lines, LineSpec(DailyPnLLine.NET_PROFIT, "Net profit", ZERO, ZERO, np))
    for spec in lines:
        spec.percent_of_gross = _pct(spec.amount_total, gross)

    totals = {
        "gross_sales": gross,
        "gross_sales_food": food,
        "gross_sales_drinks": drinks,
        "round_off": round_off_amount,
        "net_sales": net,
        "cogs": cogs,
        "cogs_drinks": cogs,
        "kitchen_consumption": consumption,
        "total_direct_expenses": direct_total.quantize(TWO),
        "gross_profit": gp,
        "total_employee_costs": employee_total.quantize(TWO),
        "depreciation": depreciation,
        "cash_variance": variance,
        "total_indirect_expenses": indirect_total.quantize(TWO),
        "prime_cost": prime,
        "net_profit": np,
        "gross_sales_percent": _pct(gross, gross) if gross else ZERO,
        "round_off_percent": _pct(round_off_amount, gross),
        "net_sales_percent": _pct(net, gross),
        "cogs_percent": _pct(cogs, gross),
        "kitchen_consumption_percent": _pct(consumption, gross),
        "total_direct_expenses_percent": _pct(direct_total, gross),
        "gross_profit_percent": _pct(gp, gross),
        "total_employee_costs_percent": _pct(employee_total, gross),
        "depreciation_percent": _pct(depreciation, gross),
        "cash_variance_percent": _pct(variance, gross),
        "total_indirect_expenses_percent": _pct(indirect_total, gross),
        "prime_cost_percent": _pct(prime, gross),
        "net_profit_percent": _pct(np, gross),
    }
    return Computation(totals=totals, lines=lines, cogs_rows=cogs_rows, consumption_rows=consumption_rows)


@transaction.atomic
def submit_daily_pnl(pnl, actor=None):
    """Snapshot computation onto the document and flip it SUBMITTED. No GL."""
    locked = DailyPnL.objects.select_for_update().get(pk=pnl.pk)
    if locked.status != DailyPnL.DRAFT:
        raise ValidationError("Only draft Daily P&L documents can be submitted.")
    FiscalYear.get_for(locked.business_date)
    config = PnLConfiguration.load()
    computation = compute_daily_pnl(locked)

    from .pnl_models import DailyPnLMaterialQty

    for row in locked.material_qtys.select_related("material").all():
        rate = row.material.rate
        DailyPnLMaterialQty.objects.filter(pk=row.pk).update(rate=rate, amount=(row.qty * rate).quantize(TWO))

    locked.lines.all().delete()
    locked.cogs_rows.all().delete()
    locked.consumption_rows.all().delete()

    gross = computation.totals["gross_sales"]
    for spec in computation.lines:
        DailyPnLLine.objects.create(
            pnl=locked,
            section=spec.section,
            label=spec.label,
            amount_food=spec.amount_food,
            amount_drinks=spec.amount_drinks,
            amount_total=spec.amount_total,
            percent_of_gross=_pct(spec.amount_total, gross),
            is_memo=spec.is_memo,
            sort_order=spec.sort_order,
            source=spec.source,
        )
    for row in computation.cogs_rows:
        DailyPnLCogsRow.objects.create(pnl=locked, department=DRINKS, **row)
    for row in computation.consumption_rows:
        DailyPnLConsumptionRow.objects.create(pnl=locked, **row)

    for name, value in computation.totals.items():
        setattr(locked, name, value)
    locked.electricity_rate = config.electricity_rate
    locked.period_start, locked.period_end = business_day_window(locked.business_date, config.business_day_start_hour)
    locked.status = DailyPnL.SUBMITTED
    locked.submitted_at = timezone.now()
    locked.submitted_by = actor
    locked._allow_submit = True
    try:
        locked.save()
    finally:
        del locked._allow_submit
    pnl.refresh_from_db()
    return pnl
