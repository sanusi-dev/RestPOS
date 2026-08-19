"""Data migration — create Supplier rows from existing purchase-receipt supplier text.

Existing ``PurchaseReceipt.supplier_name`` values become Supplier master rows
(name-matched, idempotent) and the receipts' optional ``supplier`` FK is linked.
"""

from django.db import migrations


def create_suppliers_from_receipts(apps, schema_editor):
    Supplier = apps.get_model("accounting", "Supplier")
    PurchaseReceipt = apps.get_model("inventory", "PurchaseReceipt")

    # Name-matched, idempotent: existing Suppliers are never duplicated.
    name_to_supplier = {s.supplier_name: s for s in Supplier.objects.all()}
    for receipt in PurchaseReceipt.objects.exclude(supplier_name="").order_by("pk"):
        name = receipt.supplier_name.strip()
        if not name:
            continue
        supplier = name_to_supplier.get(name)
        if supplier is None:
            supplier = Supplier.objects.create(supplier_name=name)
            name_to_supplier[name] = supplier
        if receipt.supplier_id != supplier.pk:
            receipt.supplier = supplier
            receipt.save(update_fields=["supplier"])


def reverse_noop(apps, schema_editor):
    # Reverse is a no-op: linked receipts keep their FK; Supplier rows remain.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_supplier_supplierinvoice_supplierinvoiceitem_and_more"),
        ("inventory", "0027_purchasereceipt_supplier"),
    ]

    operations = [
        migrations.RunPython(create_suppliers_from_receipts, reverse_noop),
    ]
