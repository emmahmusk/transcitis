# Item category and charge mapping

This register defines the allowed parcel item categories. All rates are intentionally **unset** until the business approves the charge schedule. Categories begin inactive and cannot be selected for a new parcel until a super administrator enters an approved charge and activates the category.

| Category | Code | Approved charge (NGN) | Status |
| --- | --- | ---: | --- |
| Documents | `documents` | Pending | Inactive |
| Clothing & accessories | `clothing-accessories` | Pending | Inactive |
| Electronics | `electronics` | Pending | Inactive |
| Food & perishables | `food-perishables` | Pending | Inactive |
| Fragile goods | `fragile-goods` | Pending | Inactive |
| Household items | `household-items` | Pending | Inactive |
| Auto parts | `auto-parts` | Pending | Inactive |
| Other | `other` | Pending | Inactive |

The super administrator maintains the authoritative list in Django Admin or through the Pricing endpoints documented in Swagger. Each parcel records its selected category and the charge in effect at registration. Do not use this mapping as a price quote until the charge schedule is approved.
