"""Read-only SQL used by the dashboard. No SELECT *; every query is parameterised.

The target facts reuse the verified Target logic (sql/targets_main.sql): the
booking level of polaris_bookings_targets joined to its staff target and
project target, with deleted rows excluded. Totals are summed from this grain,
so City / Project / Unit filters stay exact and nothing is counted twice.

Target Achieved is NOT Propone's achieved_amount: it is the Installment + Possession
money actually deposited in the month (TARGET_DEPOSITS), put on one target row per
booking. Propone's own figure is kept alongside as propone_achieved for reference.
"""

S = "propone_zameenpk.propone_zameenpk__"

# One row per staff x month x project x booking (all months, one tenant).
TARGET_FACTS = f"""
SELECT t.target_date              AS target_month,
       t.id                       AS target_id,
       t.user_id                  AS user_id,
       bt.target_project_id       AS project_target_id,
       bt.id                      AS booking_target_id,
       bt.project_id              AS project_id,
       bt.booking_id              AS booking_id,
       b.unit_id                  AS unit_id,
       b.booking_number           AS booking_number,
       b.assignee_id              AS booking_assignee_id,
       cl.full_name               AS customer,
       p.city_id                  AS city_id,
       bt.assigned_target         AS assigned,
       bt.achieved_amount         AS achieved,
       bt.due_amount              AS due_amount,
       bt.overdue_amount          AS overdue_amount,
       bt.total_receivable        AS total_receivable,
       bt.due_current_month       AS rcv_current,
       bt.receivable_30_60        AS rcv_30_60,
       bt.receivable_60_90        AS rcv_60_90,
       bt.receivable_90_plus      AS rcv_90_plus,
       bt.achieved_current_month  AS ach_current,
       bt.achieved_30_60          AS ach_30_60,
       bt.achieved_60_90          AS ach_60_90,
       bt.achieved_90_plus        AS ach_90_plus
FROM {S}polaris_bookings_targets  bt
JOIN {S}polaris_targets           t  ON t.id  = bt.target_id
JOIN {S}polaris_projects_targets  pt ON pt.id = bt.target_project_id
JOIN {S}polaris_projects          p  ON p.id  = bt.project_id
JOIN {S}polaris_bookings          b  ON b.id  = bt.booking_id
LEFT JOIN {S}polaris_clients      pc ON pc.id = b.primary_client_id
LEFT JOIN {S}clients              cl ON cl.id = pc.client_id
WHERE t.tenant_id   = %s
  AND t.deleted_at  IS NULL
  AND pt.deleted_at IS NULL
  AND bt.deleted_at IS NULL
"""

# Propone's own staff-level totals. Used as a consistency check on every load: the
# booking-level rows must add up to these exactly (they always do when the data is
# complete). A mismatch means Redshift is part-way through reloading Propone tables.
TARGET_HEADERS = f"""
SELECT t.id AS target_id, t.assigned_target_amount AS assigned, t.achieved_amount AS achieved
FROM {S}polaris_targets t
WHERE t.tenant_id = %s
  AND t.deleted_at IS NULL
"""

# Staff hierarchy: report_to_id = manager's users.id, ancestry = path of hierarchy ids.
HIERARCHY = f"""
SELECT h.id           AS hierarchy_id,
       h.user_id      AS user_id,
       h.report_to_id AS report_to_id,
       h.ancestry     AS ancestry
FROM {S}hierarchies h
WHERE h.tenant_id = %s
  AND h.deleted_at IS NULL
"""

USERS = f"""
SELECT u.id AS user_id, u.name AS name
FROM {S}users u
WHERE u.tenant_id = %s
"""

PROJECTS = f"""
SELECT p.id AS project_id, p.name AS project_name, p.city_id AS city_id
FROM {S}polaris_projects p
WHERE p.tenant_id = %s
"""

UNITS = f"""
SELECT u.id AS unit_id, u.unit_number AS unit_number, u.name AS unit_name
FROM {S}polaris_units u
WHERE u.tenant_id = %s
"""

# Change detection: when and how much of each source table was last loaded from Propone.
# Redshift receives Propone changes in batches (about hourly), so the heavy reload only runs
# when this signature changes. COUNT catches removed rows, MAX(inserted_date) catches new and
# updated ones.
SIGNATURE_TABLES = ("polaris_targets", "polaris_projects_targets", "polaris_bookings_targets", "polaris_bookings",
                    "polaris_payments", "polaris_bookings_payments", "polaris_adjusted_installments",
                    "polaris_installments", "hierarchies", "users", "polaris_projects", "polaris_units",
                    "polaris_clients", "clients", "statuses")
SOURCE_SIGNATURE = "\nUNION ALL\n".join(
    f"SELECT '{t}' AS tbl, MAX(inserted_date) AS last_loaded, COUNT(1) AS n FROM {S}{t}" for t in SIGNATURE_TABLES)

FRESHNESS = f"""
SELECT MAX(bt.inserted_date) AS last_loaded, MAX(bt.updated_at) AS last_changed
FROM {S}polaris_bookings_targets bt
"""

# Allocation rows whose installment was deleted (e.g. a regenerated payment plan) are
# skipped: polaris_adjusted_installments has no deleted flag, and keeping them would count
# the same payment twice (seen on ZAX-0504, Sept 2026: one 14.9M payment on two plans).
LIVE_ALLOCATIONS = f"""(
    SELECT a.id, a.booking_payment_id, a.installment_id, a.amount, a.overdue_charges,
           a.income_tax, a.sales_tax, a.cancellation_fee
    FROM {S}polaris_adjusted_installments a
    JOIN {S}polaris_installments li ON li.id = a.installment_id
    WHERE li.deleted_at IS NULL)"""

# Payments deposited in the target month (Pakistan time, stored as UTC) with a
# Verified or Received status, for bookings that are in that month's targets,
# split into the installments they were allocated to.
PAYMENT_ALLOCATIONS = f"""
SELECT bp.booking_id           AS booking_id,
       bp.id                   AS booking_payment_id,
       bp.amount               AS payment_amount,
       p.id                    AS payment_id,
       p.reference_number      AS payment_reference,
       p.deposit_date          AS deposit_date_utc,
       p.payment_type          AS payment_type,
       s.name                  AS payment_status,
       ai.id                   AS allocation_id,
       ai.amount               AS allocated_amount,
       ai.overdue_charges      AS late_charges,
       ai.income_tax           AS income_tax,
       ai.sales_tax            AS sales_tax,
       ai.cancellation_fee     AS cancellation_fee,
       i.id                    AS installment_id,
       i.name                  AS installment_name,
       i.installment_type      AS installment_type,
       i.due_date              AS installment_due_date
FROM {S}polaris_bookings_payments bp
JOIN {S}polaris_payments p               ON p.id  = bp.payment_id
LEFT JOIN {S}statuses s                  ON s.id  = p.status_id
LEFT JOIN {LIVE_ALLOCATIONS} ai ON ai.booking_payment_id = bp.id
LEFT JOIN {S}polaris_installments i      ON i.id  = ai.installment_id
WHERE p.deleted_at IS NULL
  AND s.name IN ('Verified', 'Received')
  AND p.deposit_date >= %s
  AND p.deposit_date <  %s
  AND bp.booking_id IN (
        SELECT bt.booking_id
        FROM {S}polaris_bookings_targets bt
        JOIN {S}polaris_targets t ON t.id = bt.target_id
        JOIN {S}polaris_projects_targets pt ON pt.id = bt.target_project_id
        WHERE t.tenant_id = %s
          AND t.target_date = %s
          AND t.deleted_at IS NULL
          AND pt.deleted_at IS NULL
          AND bt.deleted_at IS NULL)
"""

# Money received on bookings that are NOT in any staff target for the month
# ("not tagged in target"). Same payment rules as above; the booking's own
# assignee is used for staff attribution because there is no target owner.
UNTAGGED_PAYMENTS = f"""
SELECT bp.booking_id           AS booking_id,
       bp.id                   AS booking_payment_id,
       bp.amount               AS payment_amount,
       p.id                    AS payment_id,
       p.reference_number      AS payment_reference,
       p.deposit_date          AS deposit_date_utc,
       p.payment_type          AS payment_type,
       s.name                  AS payment_status,
       ai.id                   AS allocation_id,
       ai.amount               AS allocated_amount,
       ai.overdue_charges      AS late_charges,
       ai.income_tax           AS income_tax,
       ai.sales_tax            AS sales_tax,
       ai.cancellation_fee     AS cancellation_fee,
       i.id                    AS installment_id,
       i.name                  AS installment_name,
       i.installment_type      AS installment_type,
       i.due_date              AS installment_due_date,
       b.booking_number        AS booking_number,
       b.project_id            AS project_id,
       b.unit_id               AS unit_id,
       b.assignee_id           AS assignee_id,
       bs.name                 AS booking_status,
       cl.full_name            AS customer
FROM {S}polaris_bookings_payments bp
JOIN {S}polaris_payments p               ON p.id  = bp.payment_id
JOIN {S}polaris_bookings b               ON b.id  = bp.booking_id
LEFT JOIN {S}polaris_clients pc          ON pc.id = b.primary_client_id
LEFT JOIN {S}clients cl                  ON cl.id = pc.client_id
LEFT JOIN {S}statuses s                  ON s.id  = p.status_id
LEFT JOIN {S}statuses bs                 ON bs.id = b.status_id
LEFT JOIN {LIVE_ALLOCATIONS} ai ON ai.booking_payment_id = bp.id
LEFT JOIN {S}polaris_installments i      ON i.id  = ai.installment_id
WHERE p.deleted_at IS NULL
  AND b.deleted_at IS NULL
  AND b.tenant_id = %s
  AND s.name IN ('Verified', 'Received')
  AND p.deposit_date >= %s
  AND p.deposit_date <  %s
  AND bp.booking_id NOT IN (
        SELECT bt.booking_id
        FROM {S}polaris_bookings_targets bt
        JOIN {S}polaris_targets t ON t.id = bt.target_id
        JOIN {S}polaris_projects_targets pt ON pt.id = bt.target_project_id
        WHERE t.tenant_id = %s
          AND t.target_date = %s
          AND t.deleted_at IS NULL
          AND pt.deleted_at IS NULL
          AND bt.deleted_at IS NULL)
"""

# Target Achieved (actual): money deposited in the target month (PKT) with status Verified or
# Received on bookings in that month's target list, per installment it was allocated to.
# Only the principal part of each allocation is returned (late charges and taxes are other
# categories). Python applies categories.categorize() and keeps Installment + Possession,
# exactly the same rule as the "Payments by category" section.
TARGET_DEPOSITS = f"""
SELECT tl.target_month          AS target_month,
       bp.booking_id            AS booking_id,
       i.name                   AS installment_name,
       i.installment_type       AS installment_type,
       i.due_date               AS installment_due_date,
       SUM(COALESCE(ai.amount, 0) - COALESCE(ai.overdue_charges, 0) - COALESCE(ai.income_tax, 0)
           - COALESCE(ai.sales_tax, 0) - COALESCE(ai.cancellation_fee, 0)) AS principal
FROM {S}polaris_bookings_payments bp
JOIN {S}polaris_payments p          ON p.id = bp.payment_id
JOIN {S}statuses s                  ON s.id = p.status_id
JOIN {LIVE_ALLOCATIONS} ai ON ai.booking_payment_id = bp.id
JOIN {S}polaris_installments i      ON i.id = ai.installment_id
JOIN (SELECT DISTINCT t.target_date AS target_month, bt.booking_id
      FROM {S}polaris_bookings_targets bt
      JOIN {S}polaris_targets t ON t.id = bt.target_id
      JOIN {S}polaris_projects_targets pt ON pt.id = bt.target_project_id
      WHERE t.tenant_id = %s
        AND t.deleted_at IS NULL
        AND pt.deleted_at IS NULL
        AND bt.deleted_at IS NULL) tl
  ON tl.booking_id = bp.booking_id
 AND tl.target_month = TRUNC(DATE_TRUNC('month', DATEADD(hour, 5, p.deposit_date)))
WHERE p.deleted_at IS NULL
  AND s.name IN ('Verified', 'Received')
GROUP BY 1, 2, 3, 4, 5
"""

# Manually linked payments (backend/payment_links.json): three one-row lookups, so the cluster
# never plans a large join for them. A link is ignored as soon as Redshift has any booking link
# for the payment (MANUAL_PAYMENT_LINKED), so a manual link can never double count.
MANUAL_PAYMENT = f"""
SELECT p.id                    AS payment_id,
       p.amount                AS payment_amount,
       p.reference_number      AS payment_reference,
       p.deposit_date          AS deposit_date_utc,
       p.payment_type          AS payment_type,
       s.name                  AS payment_status
FROM {S}polaris_payments p
JOIN {S}statuses s ON s.id = p.status_id
WHERE p.id = %s
  AND p.tenant_id = %s
  AND p.deleted_at IS NULL
  AND s.name IN ('Verified', 'Received')
"""

MANUAL_PAYMENT_LINKED = f"""
SELECT COUNT(1) AS n
FROM {S}polaris_bookings_payments bp
WHERE bp.payment_id = %s
"""

MANUAL_BOOKING = f"""
SELECT b.id                    AS booking_id,
       b.booking_number        AS booking_number,
       b.project_id            AS project_id,
       b.unit_id               AS unit_id,
       b.assignee_id           AS assignee_id,
       bs.name                 AS booking_status,
       cl.full_name            AS customer
FROM {S}polaris_bookings b
LEFT JOIN {S}statuses bs        ON bs.id = b.status_id
LEFT JOIN {S}polaris_clients pc ON pc.id = b.primary_client_id
LEFT JOIN {S}clients cl         ON cl.id = pc.client_id
WHERE b.booking_number = %s
  AND b.tenant_id = %s
  AND b.deleted_at IS NULL
"""

MANUAL_INSTALLMENT = f"""
SELECT i.id                    AS installment_id,
       i.name                  AS installment_name,
       i.installment_type      AS installment_type,
       i.due_date              AS installment_due_date
FROM {S}polaris_installments i
WHERE i.booking_id = %s
  AND i.name = %s
  AND i.deleted_at IS NULL
"""

# Every raw installment name, for reviewing the category mapping.
INSTALLMENT_NAMES = f"""
SELECT i.name AS installment_name, i.installment_type AS installment_type, COUNT(1) AS n
FROM {S}polaris_installments i
WHERE i.tenant_id = %s
  AND i.deleted_at IS NULL
GROUP BY 1, 2
"""
