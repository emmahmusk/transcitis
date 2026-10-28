# Item category and charge mapping

The pricing screen contains the editable category charges and route tariff settings. Starter amounts are provided so staff can trial parcel estimates immediately; they are **illustrative defaults**, not a final commercial tariff. The migration fills missing category rates and preserves any charges that were already configured. A super administrator should confirm or replace these amounts before using estimates as customer commitments.

| Category | Code | Starter category charge (NGN) |
| --- | --- | ---: |
| Documents | `documents` | 1,000 |
| Clothing & accessories | `clothing-accessories` | 1,500 |
| Electronics | `electronics` | 2,500 |
| Food & perishables | `food-perishables` | 2,000 |
| Fragile goods | `fragile-goods` | 2,500 |
| Household items | `household-items` | 2,000 |
| Auto parts | `auto-parts` | 2,500 |
| Other | `other` | 1,500 |

With automatic pricing enabled, an exact route/category/service rule takes priority. If no exact rule exists, the system adds the selected category charge to the default route fee and relevant weight, declared-value, doorstep and extra-item charges, then applies the minimum charge. The super administrator can adjust the default values under **Category charges → Automatic charge settings**.

With automatic pricing disabled, registration uses only the selected category's flat charge, preserving the previous charging method. Market-value lookup is also skipped. In either mode, a Google grounded market-value result is a separate suggestion and is never treated as the item's declared value without staff confirmation.

The starting default route fee is ₦1,000, with 1 kg included, ₦500 per additional kg, 1% of declared value, ₦1,500 doorstep delivery, ₦250 per extra item and ₦1,500 minimum charge. These figures are provisional operating defaults and should be reviewed against actual route costs.
