"""Synthetic HDFC dataset. Pure data literals — no DB access, no side effects.

Foreign keys are expressed as 1-based indices into the list they point at (e.g. a
transaction's `customer_id` of 3 means "the 3rd entry in CUSTOMERS"). `db.seed` remaps
these to real serial IDs after insert.

The hard invariant here is that **every reference number quoted in a Type 2 email body
must exist in TRANSACTIONS**, otherwise data_retrieval_agent finds nothing and the demo
looks broken. `validate()` at the bottom enforces that, and db.seed calls it before
inserting anything.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# All timestamps are relative to this, so the dataset always looks "recent" in the UI.
IST = timezone(timedelta(hours=5, minutes=30))
BASE = datetime(2026, 7, 28, 9, 0, tzinfo=IST)


def _ago(hours: float) -> datetime:
    return BASE - timedelta(hours=hours)


# ---------------------------------------------------------------------------
# PRODUCTS (15)
# ---------------------------------------------------------------------------
PRODUCTS = [
    {
        "name": "HDFC SavingsMax Account",
        "category": "savings",
        "description": "A premium savings account with a higher average balance requirement, bundled insurance and unlimited free ATM access across banks.",
        "key_features": [
            "Average Monthly Balance of Rs 25,000 (urban)",
            "Unlimited free ATM withdrawals at any bank ATM",
            "Complimentary personal accident cover of Rs 10 lakh",
            "Free Platinum debit card with higher daily limits",
            "Auto-sweep into fixed deposit above Rs 1 lakh",
        ],
        "eligibility": "Resident individuals aged 18 and above, sole or joint. Valid KYC documents required.",
        "interest_rate": 3.00,
        "fees": "Non-maintenance charge of Rs 600 per quarter if AMB falls below Rs 25,000. Debit card annual fee Rs 750 plus GST.",
    },
    {
        "name": "HDFC Salary Account - Classic",
        "category": "salary",
        "description": "A zero-balance salary account for employees of companies with a corporate salary tie-up.",
        "key_features": [
            "Zero minimum balance requirement",
            "Free unlimited NEFT, RTGS and IMPS on net banking",
            "Free chequebook and passbook",
            "Overdraft of up to 2x net monthly salary after 6 months",
            "Preferential pricing on personal and car loans",
        ],
        "eligibility": "Salaried individuals whose employer has an active corporate salary arrangement with the bank. Minimum net salary credit of Rs 25,000 per month.",
        "interest_rate": 3.00,
        "fees": "Nil account maintenance charges while salary credit is active. Reverts to a Regular Savings Account if no salary credit for 3 consecutive months.",
    },
    {
        "name": "HDFC Smart Business Current Account",
        "category": "current",
        "description": "A current account for small and mid-sized businesses, with generous free cash deposit and NEFT/RTGS limits.",
        "key_features": [
            "Free cash deposit up to Rs 12 lakh per month",
            "Free NEFT and RTGS through net banking",
            "Dedicated relationship manager above Rs 5 lakh AMB",
            "Integrated payment gateway and POS options",
            "Doorstep banking for cash and cheque pickup",
        ],
        "eligibility": "Sole proprietorships, partnerships, LLPs and private limited companies with valid GST registration and business proof.",
        "interest_rate": None,
        "fees": "Average Monthly Balance of Rs 1 lakh. Non-maintenance charge Rs 1,500 per month. Cash deposit beyond the free limit charged at Rs 3.50 per Rs 1,000.",
    },
    {
        "name": "HDFC NRE Savings Account",
        "category": "nri",
        "description": "A rupee-denominated savings account for Non-Resident Indians to park overseas earnings, with fully repatriable principal and interest.",
        "key_features": [
            "Principal and interest fully repatriable",
            "Interest earned is tax-free in India",
            "Free international debit card",
            "Joint holding permitted with a resident close relative",
            "Free inward remittance through partner exchange houses",
        ],
        "eligibility": "Non-Resident Indians and Persons of Indian Origin holding a valid passport and visa or residence permit. Overseas address proof mandatory.",
        "interest_rate": 3.00,
        "fees": "Average Monthly Balance of Rs 10,000. Outward remittance charges Rs 500 plus GST per transaction.",
    },
    {
        "name": "HDFC Fixed Deposit - Standard",
        "category": "fixed_deposit",
        "description": "A regular term deposit for tenures from 7 days to 10 years, with flexible interest payout options.",
        "key_features": [
            "Tenure from 7 days to 10 years",
            "Minimum deposit of Rs 5,000",
            "Monthly, quarterly or cumulative interest payout",
            "Overdraft of up to 90 percent of deposit value",
            "Auto-renewal facility on maturity",
        ],
        "eligibility": "Resident individuals, HUFs, sole proprietorships, partnerships and companies. An existing savings or current account is required for interest credit.",
        "interest_rate": 7.10,
        "fees": "No opening or maintenance charges. Premature withdrawal attracts a 1 percent penalty on the applicable rate.",
    },
    {
        "name": "HDFC Senior Citizen Fixed Deposit",
        "category": "fixed_deposit",
        "description": "A term deposit for depositors aged 60 and above, carrying an additional interest premium over the standard card rate.",
        "key_features": [
            "Additional 0.50 percent over the standard rate",
            "Extra 0.25 percent on the 5-year Care tenure",
            "Monthly or quarterly interest payout for regular income",
            "Nomination facility available",
            "Form 15H accepted to avoid TDS where eligible",
        ],
        "eligibility": "Resident individuals aged 60 years and above on the date of deposit. Age proof required at booking.",
        "interest_rate": 7.60,
        "fees": "No opening charges. Premature withdrawal penalty of 1 percent on the applicable rate.",
    },
    {
        "name": "HDFC 5-Year Tax Saver Fixed Deposit",
        "category": "fixed_deposit",
        "description": "A fixed deposit with a mandatory 5-year lock-in that qualifies for deduction under Section 80C of the Income Tax Act.",
        "key_features": [
            "Deduction of up to Rs 1.5 lakh per year under Section 80C",
            "Fixed 5-year lock-in period",
            "Minimum Rs 100, maximum Rs 1.5 lakh per financial year",
            "Cumulative or quarterly payout options",
            "Nomination facility available",
        ],
        "eligibility": "Resident individuals and HUFs with a valid PAN. First holder claims the tax benefit in a joint deposit.",
        "interest_rate": 7.00,
        "fees": "No charges. Premature withdrawal and loan against deposit are not permitted during the 5-year lock-in.",
    },
    {
        "name": "HDFC Recurring Deposit",
        "category": "recurring_deposit",
        "description": "A disciplined monthly savings product where a fixed instalment is invested every month at a pre-agreed rate.",
        "key_features": [
            "Instalments from Rs 1,000 per month",
            "Tenure from 6 months to 10 years",
            "Standing instruction from your savings account",
            "Same interest rate as a fixed deposit of the same tenure",
            "Rate locked in for the full tenure at booking",
        ],
        "eligibility": "Resident individuals and HUFs holding a savings or current account with the bank.",
        "interest_rate": 7.00,
        "fees": "No opening charges. Rs 100 penalty per delayed instalment. Premature closure attracts a 1 percent rate penalty.",
    },
    {
        "name": "HDFC Home Loan",
        "category": "home_loan",
        "description": "A secured loan for purchase, construction, extension or improvement of a residential property, with tenures up to 30 years.",
        "key_features": [
            "Tenure of up to 30 years",
            "Funding of up to 90 percent of property value for loans up to Rs 30 lakh",
            "Choice of fixed or floating rate linked to the repo rate",
            "No prepayment charges on floating rate loans for individuals",
            "Tax benefit on principal under 80C and interest under Section 24",
        ],
        "eligibility": "Salaried applicants aged 21 to 60 and self-employed aged 21 to 65, with a minimum net monthly income of Rs 25,000 and a credit score of 700 or above.",
        "interest_rate": 8.50,
        "fees": "Processing fee of up to 0.50 percent of the loan amount or Rs 3,000, whichever is higher, plus GST. Legal and technical valuation charges at actuals.",
    },
    {
        "name": "HDFC Personal Loan",
        "category": "personal_loan",
        "description": "An unsecured loan for personal needs such as weddings, travel, medical expenses or debt consolidation, with no end-use restriction.",
        "key_features": [
            "Loan amount from Rs 50,000 to Rs 40 lakh",
            "Tenure from 12 to 72 months",
            "No collateral or guarantor required",
            "Disbursal in as little as 4 hours for pre-approved customers",
            "Optional insurance cover on the outstanding balance",
        ],
        "eligibility": "Salaried individuals aged 21 to 60 with minimum net monthly income of Rs 25,000, at least 2 years of total work experience and a credit score of 720 or above.",
        "interest_rate": 10.85,
        "fees": "Processing fee of up to 2.50 percent of the loan amount plus GST. Prepayment charges of 4 percent on the outstanding principal if foreclosed within 12 months.",
    },
    {
        "name": "HDFC Car Loan",
        "category": "car_loan",
        "description": "A secured loan for the purchase of new or pre-owned passenger cars, with the vehicle hypothecated to the bank.",
        "key_features": [
            "Funding of up to 100 percent of the ex-showroom price on select models",
            "Tenure from 12 to 84 months",
            "Pre-approved offers with instant sanction for existing customers",
            "Step-up and balloon repayment options",
            "Loan against an existing car also available",
        ],
        "eligibility": "Salaried applicants aged 21 to 60 with a minimum annual income of Rs 3 lakh, or self-employed with a minimum annual income of Rs 3 lakh and 2 years in business.",
        "interest_rate": 9.20,
        "fees": "Processing fee of Rs 3,500 to Rs 8,000 depending on loan amount, plus GST. Foreclosure charge of 3 percent to 6 percent of outstanding principal.",
    },
    {
        "name": "HDFC Education Loan",
        "category": "education_loan",
        "description": "A loan covering tuition, living and travel costs for higher education in India or abroad, with repayment beginning after a moratorium.",
        "key_features": [
            "Up to Rs 20 lakh for study in India and Rs 50 lakh for study abroad",
            "Moratorium of course duration plus 12 months",
            "Collateral-free up to Rs 7.5 lakh",
            "Tax deduction on interest paid under Section 80E",
            "Sanction letter issued before admission for visa purposes",
        ],
        "eligibility": "Indian resident students aged 16 to 35 with a confirmed admission to a recognised institution, and a co-applicant parent or guardian with a stable income.",
        "interest_rate": 9.50,
        "fees": "Processing fee of up to 1 percent of the loan amount plus GST, refundable on disbursal for study-in-India cases. No prepayment charges.",
    },
    {
        "name": "HDFC Regalia Gold Credit Card",
        "category": "credit_card",
        "description": "A premium lifestyle and travel credit card with accelerated reward points, airport lounge access and complimentary memberships.",
        "key_features": [
            "4 reward points per Rs 150 spent, 20x on select partner brands",
            "12 complimentary domestic and 6 international lounge visits per year",
            "Complimentary Club Vistara Silver and MMT Black Elite membership",
            "Air accident cover of Rs 1 crore",
            "1 percent fuel surcharge waiver",
        ],
        "eligibility": "Salaried applicants with a gross monthly income above Rs 1 lakh, or self-employed with ITR above Rs 12 lakh per annum. Credit score of 750 or above.",
        "interest_rate": 43.20,
        "fees": "Joining and annual fee of Rs 2,500 plus GST, waived on annual spends of Rs 4 lakh. Finance charge of 3.60 percent per month on revolving balances.",
    },
    {
        "name": "HDFC MoneyBack+ Credit Card",
        "category": "credit_card",
        "description": "An entry-level cashback-oriented credit card aimed at everyday online and offline spending.",
        "key_features": [
            "10x CashPoints on Amazon, Flipkart, Swiggy and Big Basket",
            "5x CashPoints on EMI spends at merchant outlets",
            "Rs 500 gift voucher on quarterly spends of Rs 50,000",
            "Up to 20 percent discount at partner restaurants",
            "Interest-free credit period of up to 50 days",
        ],
        "eligibility": "Salaried applicants aged 21 to 60 with gross monthly income above Rs 25,000, or self-employed aged 21 to 65 with ITR above Rs 6 lakh per annum.",
        "interest_rate": 43.20,
        "fees": "Joining and renewal fee of Rs 500 plus GST, waived on annual spends of Rs 50,000. Finance charge of 3.60 percent per month on revolving balances.",
    },
    {
        "name": "HDFC Demat and Trading Account",
        "category": "demat",
        "description": "A three-in-one account linking savings, demat and trading, allowing settlement of equity and mutual fund trades without manual fund transfers.",
        "key_features": [
            "Three-in-one linkage of savings, demat and trading accounts",
            "Trade in equity, derivatives, IPOs, ETFs and mutual funds",
            "Instant fund transfer between savings and trading account",
            "Research reports and advisory available on the platform",
            "Electronic delivery instruction slips, no physical DIS booklet needed",
        ],
        "eligibility": "Resident individuals aged 18 and above with a valid PAN, Aadhaar and an HDFC savings account. In-person verification is mandatory.",
        "interest_rate": None,
        "fees": "Account opening free. Annual maintenance charge of Rs 750 plus GST from the second year. Brokerage of 0.50 percent on delivery trades.",
    },
]

# ---------------------------------------------------------------------------
# CUSTOMERS (20)
# ---------------------------------------------------------------------------
CUSTOMERS = [
    {"name": "Aarav Sharma", "email": "aarav.sharma@example.com", "account_number": "50100234567801", "phone": "+91 98200 11201", "kyc_status": "verified"},
    {"name": "Diya Patel", "email": "diya.patel@example.com", "account_number": "50100234567802", "phone": "+91 98200 11202", "kyc_status": "verified"},
    {"name": "Vihaan Reddy", "email": "vihaan.reddy@example.com", "account_number": "50100234567803", "phone": "+91 98200 11203", "kyc_status": "verified"},
    {"name": "Ananya Iyer", "email": "ananya.iyer@example.com", "account_number": "50100234567804", "phone": "+91 98200 11204", "kyc_status": "pending"},
    {"name": "Arjun Mehta", "email": "arjun.mehta@example.com", "account_number": "50100234567805", "phone": "+91 98200 11205", "kyc_status": "verified"},
    {"name": "Ishaan Gupta", "email": "ishaan.gupta@example.com", "account_number": "50100234567806", "phone": "+91 98200 11206", "kyc_status": "verified"},
    {"name": "Saanvi Nair", "email": "saanvi.nair@example.com", "account_number": "50100234567807", "phone": "+91 98200 11207", "kyc_status": "expired"},
    {"name": "Kabir Singh", "email": "kabir.singh@example.com", "account_number": "50100234567808", "phone": "+91 98200 11208", "kyc_status": "verified"},
    {"name": "Myra Joshi", "email": "myra.joshi@example.com", "account_number": "50100234567809", "phone": "+91 98200 11209", "kyc_status": "verified"},
    {"name": "Reyansh Kulkarni", "email": "reyansh.kulkarni@example.com", "account_number": "50100234567810", "phone": "+91 98200 11210", "kyc_status": "verified"},
    {"name": "Aditi Rao", "email": "aditi.rao@example.com", "account_number": "50100234567811", "phone": "+91 98200 11211", "kyc_status": "pending"},
    {"name": "Rohan Desai", "email": "rohan.desai@example.com", "account_number": "50100234567812", "phone": "+91 98200 11212", "kyc_status": "verified"},
    {"name": "Neha Bhatt", "email": "neha.bhatt@example.com", "account_number": "50100234567813", "phone": "+91 98200 11213", "kyc_status": "verified"},
    {"name": "Karthik Menon", "email": "karthik.menon@example.com", "account_number": "50100234567814", "phone": "+91 98200 11214", "kyc_status": "verified"},
    {"name": "Priyanka Chawla", "email": "priyanka.chawla@example.com", "account_number": "50100234567815", "phone": "+91 98200 11215", "kyc_status": "expired"},
    {"name": "Siddharth Ranade", "email": "siddharth.ranade@example.com", "account_number": "50100234567816", "phone": "+91 98200 11216", "kyc_status": "verified"},
    {"name": "Tanvi Kapoor", "email": "tanvi.kapoor@example.com", "account_number": "50100234567817", "phone": "+91 98200 11217", "kyc_status": "verified"},
    {"name": "Manish Agarwal", "email": "manish.agarwal@example.com", "account_number": "50100234567818", "phone": "+91 98200 11218", "kyc_status": "verified"},
    {"name": "Sneha Pillai", "email": "sneha.pillai@example.com", "account_number": "50100234567819", "phone": "+91 98200 11219", "kyc_status": "pending"},
    {"name": "Varun Malhotra", "email": "varun.malhotra@example.com", "account_number": "50100234567820", "phone": "+91 98200 11220", "kyc_status": "verified"},
]

# ---------------------------------------------------------------------------
# TRANSACTIONS (60)
# Compact tuples, expanded below:
#   (customer_idx, type, amount, currency, status, reference_no, swift_ref,
#    initiated_hours_ago, updated_hours_ago)
# swift_ref is populated only for type='swift'.
# ---------------------------------------------------------------------------
_TXN_ROWS = [
    # --- NEFT (15) ---
    (1, "neft", 45000.00, "INR", "completed", "NEFT2026070101", None, 120, 118),
    (1, "neft", 12500.00, "INR", "in_transit", "NEFT2026070102", None, 8, 6),
    (2, "neft", 78000.00, "INR", "completed", "NEFT2026070103", None, 96, 94),
    (3, "neft", 5400.00, "INR", "failed", "NEFT2026070104", None, 52, 50),
    (4, "neft", 150000.00, "INR", "pending", "NEFT2026070105", None, 14, 14),
    (5, "neft", 22000.00, "INR", "completed", "NEFT2026070106", None, 200, 198),
    (6, "neft", 9800.00, "INR", "completed", "NEFT2026070107", None, 168, 166),
    (7, "neft", 64000.00, "INR", "in_transit", "NEFT2026070108", None, 20, 18),
    (8, "neft", 31500.00, "INR", "completed", "NEFT2026070109", None, 72, 70),
    (9, "neft", 4200.00, "INR", "failed", "NEFT2026070110", None, 44, 43),
    (10, "neft", 88000.00, "INR", "completed", "NEFT2026070111", None, 240, 238),
    (11, "neft", 17600.00, "INR", "pending", "NEFT2026070112", None, 5, 5),
    (12, "neft", 250000.00, "INR", "completed", "NEFT2026070113", None, 144, 142),
    (13, "neft", 6300.00, "INR", "completed", "NEFT2026070114", None, 312, 310),
    (14, "neft", 41000.00, "INR", "in_transit", "NEFT2026070115", None, 11, 9),

    # --- RTGS (15) ---
    (2, "rtgs", 520000.00, "INR", "completed", "RTGS2026070201", None, 100, 99),
    (3, "rtgs", 1250000.00, "INR", "in_transit", "RTGS2026070202", None, 6, 4),
    (5, "rtgs", 300000.00, "INR", "completed", "RTGS2026070203", None, 216, 215),
    (6, "rtgs", 750000.00, "INR", "pending", "RTGS2026070204", None, 3, 3),
    (8, "rtgs", 425000.00, "INR", "completed", "RTGS2026070205", None, 130, 129),
    (10, "rtgs", 980000.00, "INR", "failed", "RTGS2026070206", None, 60, 58),
    (12, "rtgs", 610000.00, "INR", "completed", "RTGS2026070207", None, 288, 287),
    (13, "rtgs", 205000.00, "INR", "in_transit", "RTGS2026070208", None, 16, 14),
    (14, "rtgs", 1500000.00, "INR", "completed", "RTGS2026070209", None, 180, 179),
    (15, "rtgs", 340000.00, "INR", "pending", "RTGS2026070210", None, 9, 9),
    (16, "rtgs", 875000.00, "INR", "completed", "RTGS2026070211", None, 264, 263),
    (17, "rtgs", 260000.00, "INR", "completed", "RTGS2026070212", None, 336, 335),
    (18, "rtgs", 1100000.00, "INR", "in_transit", "RTGS2026070213", None, 22, 20),
    (19, "rtgs", 450000.00, "INR", "failed", "RTGS2026070214", None, 78, 76),
    (20, "rtgs", 690000.00, "INR", "completed", "RTGS2026070215", None, 152, 151),

    # --- Internal transfers (15) ---
    (1, "transfer", 15000.00, "INR", "completed", "TRF2026070301", None, 30, 30),
    (2, "transfer", 2500.00, "INR", "completed", "TRF2026070302", None, 48, 48),
    (3, "transfer", 60000.00, "INR", "pending", "TRF2026070303", None, 2, 2),
    (4, "transfer", 8900.00, "INR", "completed", "TRF2026070304", None, 90, 90),
    (5, "transfer", 120000.00, "INR", "failed", "TRF2026070305", None, 36, 35),
    (7, "transfer", 3300.00, "INR", "completed", "TRF2026070306", None, 110, 110),
    (9, "transfer", 47000.00, "INR", "completed", "TRF2026070307", None, 64, 64),
    (10, "transfer", 1800.00, "INR", "completed", "TRF2026070308", None, 190, 190),
    (11, "transfer", 95000.00, "INR", "in_transit", "TRF2026070309", None, 7, 6),
    (13, "transfer", 5600.00, "INR", "completed", "TRF2026070310", None, 250, 250),
    (15, "transfer", 33000.00, "INR", "completed", "TRF2026070311", None, 128, 128),
    (16, "transfer", 7400.00, "INR", "pending", "TRF2026070312", None, 4, 4),
    (17, "transfer", 210000.00, "INR", "completed", "TRF2026070313", None, 300, 300),
    (18, "transfer", 12000.00, "INR", "failed", "TRF2026070314", None, 55, 54),
    (20, "transfer", 26500.00, "INR", "completed", "TRF2026070315", None, 84, 84),

    # --- SWIFT / cross-border (15) ---
    (1, "swift", 12000.00, "USD", "in_transit", "SWF2026070401", "HDFCINBBXXX4401", 30, 26),
    (3, "swift", 8500.00, "USD", "completed", "SWF2026070402", "HDFCINBBXXX4402", 168, 160),
    (4, "swift", 15000.00, "EUR", "pending", "SWF2026070403", "HDFCINBBXXX4403", 12, 12),
    (5, "swift", 22000.00, "USD", "completed", "SWF2026070404", "HDFCINBBXXX4404", 336, 328),
    (6, "swift", 4700.00, "GBP", "in_transit", "SWF2026070405", "HDFCINBBXXX4405", 40, 34),
    (8, "swift", 60000.00, "USD", "failed", "SWF2026070406", "HDFCINBBXXX4406", 96, 88),
    (9, "swift", 9200.00, "EUR", "completed", "SWF2026070407", "HDFCINBBXXX4407", 264, 256),
    (11, "swift", 31000.00, "USD", "in_transit", "SWF2026070408", "HDFCINBBXXX4408", 18, 15),
    (12, "swift", 7800.00, "SGD", "completed", "SWF2026070409", "HDFCINBBXXX4409", 200, 192),
    (14, "swift", 45000.00, "USD", "pending", "SWF2026070410", "HDFCINBBXXX4410", 5, 5),
    (16, "swift", 13400.00, "AED", "completed", "SWF2026070411", "HDFCINBBXXX4411", 144, 136),
    (17, "swift", 26000.00, "USD", "in_transit", "SWF2026070412", "HDFCINBBXXX4412", 24, 21),
    (18, "swift", 5100.00, "GBP", "completed", "SWF2026070413", "HDFCINBBXXX4413", 288, 280),
    (19, "swift", 18700.00, "EUR", "failed", "SWF2026070414", "HDFCINBBXXX4414", 72, 64),
    (20, "swift", 92000.00, "USD", "completed", "SWF2026070415", "HDFCINBBXXX4415", 216, 208),
]

TRANSACTIONS = [
    {
        "customer_id": cust_idx,
        "type": txn_type,
        "amount": amount,
        "currency": currency,
        "status": status,
        "reference_no": reference_no,
        "swift_ref": swift_ref,
        "initiated_at": _ago(init_h),
        "updated_at": _ago(upd_h),
    }
    for (cust_idx, txn_type, amount, currency, status, reference_no, swift_ref, init_h, upd_h) in _TXN_ROWS
]


# ---------------------------------------------------------------------------
# EMAILS (40) - 20 Type 1 (product info), 20 Type 2 (account/transaction specific).
# Compact tuples, expanded below:
#   (sender_email, subject, body, received_hours_ago)
# Note `intent_type` is deliberately NOT seeded - it starts NULL and is written by the
# intent_classifier node at run time. The comment above each block is ground truth for
# the smoke test, not something the app reads.
# ---------------------------------------------------------------------------
_TYPE_1_EMAILS = [
    ("aarav.sharma@example.com", "Current FD interest rates",
     "Hello,\n\nCould you please share the current interest rates on your fixed deposits for a 2-year tenure? I am also curious whether senior citizens get a better rate, as I would like to open one in my father's name.\n\nThanks,\nAarav Sharma", 2),
    ("neel.varma@example.com", "Home loan eligibility criteria",
     "Hi,\n\nI am planning to buy an apartment in Pune next year. What is the eligibility criteria for a home loan, and what is the maximum tenure you offer? My net monthly salary is around Rs 90,000.\n\nRegards,\nNeel Varma", 5),
    ("diya.patel@example.com", "Regalia Gold card benefits",
     "Hello,\n\nI keep seeing the Regalia Gold credit card advertised. What are the main benefits, and what is the annual fee? Is the fee waived if I spend a certain amount?\n\nThanks,\nDiya Patel", 7),
    ("ritika.sen@example.com", "Difference between the savings accounts",
     "Hi team,\n\nWhat is the difference between the SavingsMax account and a regular salary account? I want to understand the minimum balance requirement for each before I open one.\n\nRitika Sen", 9),
    ("vihaan.reddy@example.com", "Tax saver FD query",
     "Dear RM,\n\nI want to save tax under 80C this financial year. Do you have a fixed deposit that qualifies? What is the lock-in and can I withdraw early if I need the money?\n\nVihaan Reddy", 12),
    ("manoj.krishnan@example.com", "Personal loan interest rate and processing fee",
     "Hello,\n\nI need about Rs 8 lakh for a home renovation. What interest rate would apply on a personal loan, and what are the processing fees? Also, is there any penalty if I foreclose the loan early?\n\nManoj Krishnan", 15),
    ("ananya.iyer@example.com", "Education loan for masters abroad",
     "Hi,\n\nMy daughter has an admission offer from a university in Germany. What is the maximum education loan amount for studying abroad, and do you need collateral? When does repayment start?\n\nAnanya Iyer", 18),
    ("farhan.qureshi@example.com", "Car loan - what documents do I need",
     "Hello,\n\nI am looking at a car loan for a new vehicle worth about Rs 12 lakh. What is your current interest rate, and what is the longest tenure available?\n\nFarhan Qureshi", 21),
    ("arjun.mehta@example.com", "Recurring deposit details",
     "Hi,\n\nI would like to start a recurring deposit with a monthly instalment of Rs 5,000. What interest rate applies, and what happens if I miss a monthly instalment?\n\nArjun Mehta", 24),
    ("lakshmi.subramaniam@example.com", "NRE account for my son in Dubai",
     "Dear Sir/Madam,\n\nMy son has moved to Dubai for work. Can he open an NRE savings account, and is the interest earned taxable in India? Can the money be sent back abroad freely?\n\nLakshmi Subramaniam", 28),
    ("ishaan.gupta@example.com", "MoneyBack+ vs Regalia",
     "Hello,\n\nI am deciding between the MoneyBack+ and the Regalia Gold credit card. My monthly spend is around Rs 40,000, mostly online. Which one would you recommend and why?\n\nIshaan Gupta", 31),
    ("preeti.dubey@example.com", "Current account for my business",
     "Hi,\n\nI run a small trading business and deposit roughly Rs 8 lakh in cash every month. What current account would suit me, and what are the charges beyond the free cash deposit limit?\n\nPreeti Dubey", 34),
    ("kabir.singh@example.com", "Demat account opening charges",
     "Hello,\n\nWhat are the charges for opening a demat and trading account? Is there an annual maintenance fee, and what brokerage do you charge on delivery trades?\n\nKabir Singh", 38),
    ("suresh.pathak@example.com", "Senior citizen deposit rates",
     "Dear Sir,\n\nI am 64 years old and looking to invest my retirement corpus safely. What rate do you offer senior citizens on fixed deposits, and can I get the interest paid out monthly?\n\nSuresh Pathak", 42),
    ("myra.joshi@example.com", "Salary account features",
     "Hi,\n\nMy company is switching its payroll to your bank. What do I get with the salary account? Is there really no minimum balance, and what happens if I change jobs?\n\nMyra Joshi", 46),
    ("gaurav.thakur@example.com", "Overdraft against fixed deposit",
     "Hello,\n\nI have some money in fixed deposits. Can I take a loan or overdraft against them instead of breaking the deposit? How much of the deposit value can I borrow?\n\nGaurav Thakur", 50),
    ("reyansh.kulkarni@example.com", "Home loan - fixed or floating",
     "Hi team,\n\nShould I take a fixed rate or a floating rate home loan? Also, are there prepayment charges if I decide to pay off the loan early?\n\nReyansh Kulkarni", 55),
    ("anjali.deshmukh@example.com", "Minimum balance penalty",
     "Hello,\n\nWhat is the non-maintenance charge if my savings account balance drops below the required average monthly balance? I want to understand this before opening the account.\n\nAnjali Deshmukh", 60),
    ("aditi.rao@example.com", "Documents needed for a personal loan",
     "Hi,\n\nWhat is the minimum income and credit score you require for a personal loan? I have been employed for about 3 years and earn Rs 55,000 net per month.\n\nAditi Rao", 66),
    ("rohan.desai@example.com", "Lounge access on credit cards",
     "Hello,\n\nHow many complimentary airport lounge visits do I get on the Regalia Gold card in a year, both domestic and international? I travel quite often for work.\n\nRohan Desai", 70),
]

_TYPE_2_EMAILS = [
    # --- Serviceable: quote a reference number that exists in TRANSACTIONS ---
    ("aarav.sharma@example.com", "Status of my NEFT transfer NEFT2026070102",
     "Hello,\n\nI initiated an NEFT transfer yesterday with reference number NEFT2026070102 for Rs 12,500, but the beneficiary has not received it yet. Could you check the status and let me know when it will be credited?\n\nThanks,\nAarav Sharma", 1),
    ("vihaan.reddy@example.com", "Urgent - RTGS RTGS2026070202 not credited",
     "Dear RM,\n\nI made an RTGS transfer of Rs 12,50,000 this morning under reference RTGS2026070202. It is a time-sensitive property payment and the seller says the funds have not arrived. Please check urgently.\n\nVihaan Reddy", 3),
    ("aarav.sharma@example.com", "Where is my USD wire SWF2026070401",
     "Hi,\n\nI sent a wire transfer of USD 12,000 to my daughter in the US. The SWIFT reference is SWF2026070401. It has been more than a day. What is the current status of this remittance?\n\nAarav Sharma", 4),
    ("ananya.iyer@example.com", "NEFT NEFT2026070105 still showing pending",
     "Hello,\n\nMy NEFT of Rs 1,50,000 with reference NEFT2026070105 is still showing as pending in my statement. Can you tell me why it has not gone through and when it will be processed?\n\nAnanya Iyer", 6),
    ("saanvi.nair@example.com", "Transfer NEFT2026070108 status please",
     "Hi,\n\nCould you please confirm the status of my NEFT transaction NEFT2026070108 for Rs 64,000? My account is 50100234567807.\n\nSaanvi Nair", 8),
    ("ishaan.gupta@example.com", "RTGS2026070204 - when will it be processed",
     "Dear Sir/Madam,\n\nI submitted an RTGS request for Rs 7,50,000 under reference RTGS2026070204 earlier today. It still shows pending. What is the expected settlement time?\n\nIshaan Gupta", 10),
    ("kabir.singh@example.com", "Failed SWIFT transfer SWF2026070406",
     "Hello,\n\nMy outward remittance of USD 60,000 with SWIFT reference SWF2026070406 appears to have failed. Has the amount been credited back to my account 50100234567808, and what was the reason for the failure?\n\nKabir Singh", 13),
    ("reyansh.kulkarni@example.com", "RTGS2026070206 failed - need refund confirmation",
     "Hi,\n\nMy RTGS of Rs 9,80,000 under reference RTGS2026070206 has failed. Please confirm the reversal has been credited back to my account and share the timeline.\n\nReyansh Kulkarni", 16),
    ("aditi.rao@example.com", "SWIFT SWF2026070408 tracking",
     "Hello,\n\nCan you tell me where my remittance with SWIFT reference SWF2026070408 has reached? It is for USD 31,000 and the beneficiary bank has not confirmed receipt.\n\nAditi Rao", 19),
    ("rohan.desai@example.com", "Confirmation of NEFT2026070113",
     "Hi,\n\nPlease confirm that my NEFT of Rs 2,50,000 under reference NEFT2026070113 was successfully processed. I need a confirmation for my records.\n\nRohan Desai", 23),
    ("neha.bhatt@example.com", "RTGS2026070208 status check",
     "Dear RM,\n\nI would like an update on RTGS reference RTGS2026070208 for Rs 2,05,000. It was initiated yesterday and I have not received any confirmation.\n\nNeha Bhatt", 26),
    ("karthik.menon@example.com", "SWF2026070410 - remittance still pending",
     "Hello,\n\nMy SWIFT remittance SWF2026070410 for USD 45,000 is showing as pending. Is any additional documentation needed from my side to release it?\n\nKarthik Menon", 29),
    ("manish.agarwal@example.com", "Status of RTGS2026070213",
     "Hi,\n\nI need an update on my RTGS transfer of Rs 11,00,000, reference RTGS2026070213. The counterparty is asking for a UTR confirmation.\n\nManish Agarwal", 33),
    ("tanvi.kapoor@example.com", "Where is my wire SWF2026070412",
     "Hello,\n\nI sent USD 26,000 via SWIFT reference SWF2026070412 a day ago. The beneficiary has not received it. Please check the status and let me know.\n\nTanvi Kapoor", 36),
    ("sneha.pillai@example.com", "Failed EUR transfer SWF2026070414",
     "Dear Sir/Madam,\n\nMy EUR 18,700 remittance with reference SWF2026070414 has failed. Please tell me the reason and whether the funds have been returned to my account.\n\nSneha Pillai", 40),
    ("arjun.mehta@example.com", "Transfer TRF2026070305 did not go through",
     "Hi,\n\nAn internal transfer of Rs 1,20,000 with reference TRF2026070305 has failed. Can you check what went wrong and whether I should retry?\n\nArjun Mehta", 44),

    # --- Unserviceable: no usable reference / unknown sender / non-existent reference.
    #     These exercise the can_serve = false branch of auth_agent.
    ("diya.patel@example.com", "Money not received",
     "Hello,\n\nI sent some money a few days ago and the other person still has not received it. Can you please check what happened and sort this out? It is quite urgent.\n\nDiya Patel", 11),
    ("unknown.sender@example.com", "Problem with my transfer",
     "Hi,\n\nMy transfer is stuck. Please check the status of my account and tell me what is going on. I have been waiting for two days now.\n\nRegards", 17),
    ("myra.joshi@example.com", "Query on reference NEFT2026079999",
     "Hello,\n\nI would like to know the status of my NEFT transaction with reference number NEFT2026079999 for Rs 30,000. It does not appear in my statement.\n\nMyra Joshi", 25),
    ("varun.malhotra@example.com", "Statement discrepancy",
     "Dear RM,\n\nThere is an amount debited from my account that I do not recognise. Could you please look into my recent transactions and explain what this was for?\n\nVarun Malhotra", 48),
]

EMAILS = [
    {
        "customer_email": sender,
        "subject": subject,
        "body": body,
        "received_at": _ago(hours_ago),
        "status": "new",
        "intent_type": None,
    }
    for (sender, subject, body, hours_ago) in (_TYPE_1_EMAILS + _TYPE_2_EMAILS)
]


# ---------------------------------------------------------------------------
# Ground truth used by the smoke test. Indices are 1-based positions in EMAILS.
# ---------------------------------------------------------------------------
TYPE_1_COUNT = len(_TYPE_1_EMAILS)
TYPE_2_COUNT = len(_TYPE_2_EMAILS)

# A Type 1 email, a serviceable Type 2 email, and an unserviceable Type 2 email.
SAMPLE_TYPE_1_SUBJECT = _TYPE_1_EMAILS[0][1]
SAMPLE_TYPE_2_SERVICEABLE_SUBJECT = _TYPE_2_EMAILS[0][1]
SAMPLE_TYPE_2_SERVICEABLE_REF = "NEFT2026070102"
SAMPLE_TYPE_2_UNSERVICEABLE_SUBJECT = _TYPE_2_EMAILS[16][1]  # "Money not received"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
# Matches the reference formats this dataset uses: NEFT/RTGS/TRF/SWF + 10 digits.
_REF_IN_TEXT_RE = re.compile(r"\b(?:NEFT|RTGS|TRF|SWF)\d{10}\b")

# References deliberately quoted in emails that must NOT resolve, so the can_serve=false
# path gets exercised. Listing them explicitly keeps validate() honest — anything else
# that fails to resolve is a genuine data bug, not an intentional one.
INTENTIONALLY_UNRESOLVABLE_REFS = {"NEFT2026079999"}


def validate() -> None:
    """Fails loudly on internal inconsistencies before anything is written to Postgres.

    The expensive-to-debug failure mode this guards against is an email quoting a
    reference number that does not exist in TRANSACTIONS: the pipeline runs fine, the
    retrieval agent just silently finds nothing, and the demo looks broken for reasons
    that have nothing to do with the code.
    """
    errors: list[str] = []

    known_refs = {t["reference_no"] for t in TRANSACTIONS}
    known_swift = {t["swift_ref"] for t in TRANSACTIONS if t["swift_ref"]}

    if len(known_refs) != len(TRANSACTIONS):
        errors.append("TRANSACTIONS contains duplicate reference_no values")

    emails_by_addr = {c["email"] for c in CUSTOMERS}
    if len(emails_by_addr) != len(CUSTOMERS):
        errors.append("CUSTOMERS contains duplicate email addresses")

    accounts = {c["account_number"] for c in CUSTOMERS}
    if len(accounts) != len(CUSTOMERS):
        errors.append("CUSTOMERS contains duplicate account_number values")

    for txn in TRANSACTIONS:
        if not 1 <= txn["customer_id"] <= len(CUSTOMERS):
            errors.append(f"Transaction {txn['reference_no']} points at a non-existent customer index")
        if txn["type"] == "swift" and not txn["swift_ref"]:
            errors.append(f"SWIFT transaction {txn['reference_no']} has no swift_ref")
        if txn["type"] != "swift" and txn["swift_ref"]:
            errors.append(f"Non-SWIFT transaction {txn['reference_no']} unexpectedly has a swift_ref")

    for email in EMAILS:
        for ref in _REF_IN_TEXT_RE.findall(email["subject"] + " " + email["body"]):
            if ref in INTENTIONALLY_UNRESOLVABLE_REFS:
                continue
            if ref not in known_refs and ref not in known_swift:
                errors.append(f"Email {email['subject']!r} quotes unknown reference {ref}")

    # Account numbers quoted in email bodies should belong to a real customer.
    for email in EMAILS:
        for acct in re.findall(r"\b5010023456\d{4}\b", email["body"]):
            if acct not in accounts:
                errors.append(f"Email {email['subject']!r} quotes unknown account number {acct}")

    if errors:
        raise AssertionError("seed_data validation failed:\n  - " + "\n  - ".join(errors))
