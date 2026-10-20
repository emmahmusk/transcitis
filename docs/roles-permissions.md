# Role and permission administration

The staff application includes a superadmin-only **Roles & permissions** workspace styled with the Transcitis yellow and black interface. It manages grants for the built-in Administrator, Supervisor, Station staff, and Courier roles. Django superusers always retain full access and are not governed by this matrix.

Permission grants are stored in `RolePermission`, included in JWT access-token claims, and checked by protected API endpoints. The server continues to apply station data scopes and rules such as superadmin-only receipt reprints and courier creation. Changes are enforced against API requests immediately; staff should refresh their app or sign in again to load revised claims and navigation.

The permission catalog covers parcel view/create/update/receipt printing, trip view and management, receiving scans, handover verification, courier assignment, exception review/resolution, station user view/invitation/management, report export, and station directory access. Initial role grants are seeded by migration `0005_rolepermission`.

The matching API is grouped under **User management** in Swagger:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/roles/permissions/` | Read the role list, grouped permission catalog, and current grants. |
| `PUT` | `/api/roles/permissions/` | Replace grants for one role with `{ "role": "staff", "permissions": ["parcels.view", "trips.view"] }`. |

Only the Django superuser can read or update this matrix. Requests for unknown permission keys are rejected by the API serializer.
