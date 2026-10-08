"""What the dashboard shows, module by module.

Each entry is (id, type, short title, options). Types:
  cat    single-answer question        -> share of each answer
  multi  multiple-answer question      -> share of respondents choosing each
  num    number                        -> median / mean / distribution
  money  amount + currency             -> same, in USD and BDT
  text   open text                     -> most frequent answers (only if allowed in settings)
  channels / trust / rates             -> purpose-built views

To add, remove or rename a chart, edit this list only.
"""

CHANNELS = [
    ("01", "Bank branch or counter"),
    ("02", "Bank app or internet banking"),
    ("03", "Exchange house branch or agent"),
    ("04", "Money transfer operator (MTO)"),
    ("05", "Remittance app or website"),
    ("06", "Hundi or informal agent"),
    ("07", "Carried cash personally"),
    ("08", "Cash via relative, friend or traveller"),
    ("09", "Other method"),
]
FORMAL = ["01", "02", "03", "04", "05"]

CURRENCIES = {1: "GBP", 2: "MYR", 3: "USD", 4: "AED", 5: "SAR", 6: "QAR", 7: "BHD"}

MODULES = [
    ("A", "Respondent and household", [
        ("A1", "cat", "Gender", {}),
        ("A2", "num", "Age", {"unit": "years"}),
        ("A3", "cat", "Marital status", {}),
        ("A4", "cat", "Highest education completed", {}),
        ("A5", "cat", "Home district in Bangladesh", {"sort": True, "top": 12}),
        ("A6", "cat", "Type of area of family home", {}),
        ("A7", "num", "Family members living in Bangladesh", {"unit": "people"}),
        ("A8", "num", "Family members living with respondent abroad", {"unit": "people"}),
    ]),
    ("B", "Migration, employment and finances", [
        ("B1_YEARS", "num", "Time in destination country", {"unit": "years", "q": "B1. How long have you been living in this country? (years + months)"}),
        ("B2", "cat", "Main occupation before migrating", {"sort": True}),
        ("B3", "multi", "Training or advice before migrating", {}),
        ("B4", "cat", "Borrowed to cover migration costs", {}),
        ("B5", "cat", "Main occupation now", {"sort": True}),
        ("B6", "num", "Days worked in a typical week", {"unit": "days"}),
        ("B7", "num", "Hours worked on a typical day", {"unit": "hours"}),
        ("B8", "cat", "How income is received", {}),
        ("B9", "money", "Total income last month", {"amount": "B9_01", "currency": "B9_02"}),
        ("B10", "money", "Essential living expenses per month", {"amount": "B10_01", "currency": "B10_02"}),
        ("B11", "cat", "Residence and work authorisation", {}),
        ("B12", "cat", "Local language ability", {}),
    ]),
    ("C", "Remittance activity, amount, purpose and timing", [
        ("C1", "cat", "Sent or carried money in the past 12 months", {}),
        ("C2", "num", "Number of times money was sent in 12 months", {"unit": "times"}),
        ("C3", "money", "Total sent or carried in 12 months", {"amount": "C3_AMOUNT", "currency": "C3_CURRENCY"}),
        ("C4", "multi", "What the money was used for", {"sort": True}),
        ("C5", "multi", "When money is usually sent", {"sort": True}),
        ("C6", "multi", "Why no money was sent in 12 months", {"sort": True}),
        ("C7", "cat", "Ever sent money before the past 12 months", {}),
        ("C8_DOYOUREMEBER", "cat", "Remembers when money was last sent", {}),
        ("C8_WHICHYEAR", "cat", "Year money was last sent", {"numeric_codes": True}),
        ("CB_WHICHMONTH", "cat", "Month money was last sent", {}),
        ("C9", "cat", "Likelihood of sending money in the next 12 months", {}),
    ]),
    ("D", "Channels and most recent transaction", [
        ("D1", "channels", "Channels used in the past 12 months", {}),
        ("D2", "cat", "Channel carrying the largest total amount", {"sort": True}),
        ("D3", "cat", "When money was last sent", {}),
        ("D4", "cat", "Channel used for the most recent transaction", {"sort": True}),
        ("D5_DK", "cat", "Remembers the provider's name", {}),
        ("D5_NAME", "text", "Provider used for the most recent transaction", {}),
        ("D6", "money", "Amount sent in the most recent transaction", {"amount": "D6_AMOUNT", "currency": "D6_CURRENCY"}),
        ("D7_DK", "cat", "Knows how much the recipient received", {}),
        ("D7", "money", "Amount the recipient received", {"amount": "D7_AMOUNT_BDT", "currency": "BDT"}),
        ("D8_STATUS", "cat", "Paid a fee, commission or service charge", {}),
        ("D8", "money", "Fee paid by the sender", {"amount": "D8_AMOUNT", "currency": "D8_CURRENCY"}),
        ("FEE_PCT", "num", "Sender's fee as a share of the amount sent", {"unit": "%", "q": "D8 fee divided by D6 amount, both converted to USD. Respondents who said no fee was paid count as 0%."}),
        ("D9_STATUS", "cat", "Had other direct costs (travel, transport)", {}),
        ("D9", "money", "Other direct costs", {"amount": "D9_AMOUNT", "currency": "D9_CURRENCY"}),
        ("D10", "cat", "Time for the money to arrive", {}),
        ("D11", "cat", "How the money was received in Bangladesh", {"sort": True}),
        ("D12_STATUS", "cat", "Recipient paid a fee to receive or withdraw", {}),
        ("D12", "money", "Fee paid by the recipient", {"amount": "D12_AMOUNT_BDT", "currency": "BDT"}),
        ("D13", "cat", "Received a receipt or tracking reference", {}),
        ("D14", "cat", "Recipient received the government incentive", {}),
        ("RATES", "rates", "Exchange rates reported, BDT per unit of currency", {}),
    ]),
    ("E", "Channel choice, experience and barriers", [
        ("E1", "multi", "Reasons for choosing the method used", {"sort": True}),
        ("E2", "trust", "Trust in each method as a safe way to send money", {}),
        ("E3", "cat", "Aware of the government remittance incentive", {}),
        ("E4", "cat", "How much the incentive encourages formal channels", {}),
        ("E5", "multi", "Problems faced with formal channels", {"sort": True}),
        ("E6", "cat", "Tried a formal channel but could not complete", {}),
        ("E7", "multi", "Why the transaction could not be completed", {"sort": True}),
        ("E8", "cat", "How common hundi is among Bangladeshis they know", {}),
        ("E9", "multi", "Why people use hundi", {"sort": True}),
        ("E10_DK", "cat", "Remembers the hundi exchange rate", {}),
        ("E11_STATUS", "cat", "Paid a separate fee for the hundi transaction", {}),
        ("E11", "money", "Separate fee paid for the hundi transaction", {"amount": "E11_AMOUNT", "currency": "E11_CURRENCY"}),
        ("E12", "cat", "Had problems sending through hundi", {}),
        ("E13", "multi", "Problems experienced with hundi", {"sort": True}),
        ("E14", "cat", "Aware of advance-payment arrangements", {}),
        ("E15", "cat", "Used an advance-payment arrangement in 12 months", {}),
        ("E16", "cat", "Cost of the advance-payment arrangement", {}),
        ("E17_DK", "cat", "Remembers the fee paid for the arrangement", {}),
        ("E17", "money", "Fee paid for the arrangement", {"amount": "E17_AMOUNT", "currency": "E17_CURRENCY"}),
        ("E18", "cat", "Interest in an authorised instant-payout service", {}),
        ("E19", "cat", "Most trusted source of remittance advice", {"sort": True}),
    ]),
    ("F", "Financial and digital access", [
        ("F1", "multi", "Accounts and services held in the destination country", {}),
        ("F2", "cat", "Access to an internet-connected smartphone", {}),
        ("F3", "cat", "Able to use a banking or remittance app", {}),
        ("F4", "cat", "Would use an app to send directly to a bank or MFS account", {}),
        ("F5", "cat", "Who usually receives the money", {"sort": True}),
        ("F6", "cat", "Accounts the recipient holds", {}),
        ("F7", "cat", "How the recipient prefers to receive money", {"sort": True}),
        ("F8", "cat", "How long savings would last without income", {}),
    ]),
    ("G", "Use of remittances and policy priorities", [
        ("G1", "cat", "Share of household expenses covered by remittances", {}),
        ("G2", "cat", "Who decides how household expenses are managed", {"sort": True}),
        ("G3", "cat", "Share of last remittance still in the account after 7 days", {}),
        ("G4", "cat", "Share still in the account after 30 days", {}),
        ("G5", "multi", "How money left in the account is later used", {"sort": True}),
        ("G6", "multi", "Why money is withdrawn and used as cash", {"sort": True}),
        ("G7", "multi", "Changes that would make formal channels easier", {"sort": True}),
        ("G8", "cat", "Single most important change", {"sort": True}),
    ]),
]
