"""Permission catalog and role defaults shared by API and admin UI."""

PERMISSION_CATALOG = [
    {"key": "parcels.view", "module": "Parcels", "label": "View parcels", "description": "Search parcels and view their timelines."},
    {"key": "parcels.view_assigned", "module": "Parcels", "label": "View assigned parcels", "description": "View parcels assigned to the courier."},
    {"key": "parcels.create", "module": "Parcels", "label": "Register parcels", "description": "Create parcels at the assigned station."},
    {"key": "parcels.update", "module": "Parcels", "label": "Update parcel status", "description": "Perform parcel status updates."},
    {"key": "parcels.receipt", "module": "Receipts", "label": "Print first receipt", "description": "Print a receipt once; superadmins may reprint."},
    {"key": "trips.view", "module": "Trips", "label": "View trips", "description": "View trips in the assigned station scope."},
    {"key": "trips.manage", "module": "Trips", "label": "Create and manage trips", "description": "Build manifests, scan parcels, dispatch and mark arrivals."},
    {"key": "receiving.scan", "module": "Receiving", "label": "Scan receiving parcels", "description": "Record destination arrival scans."},
    {"key": "handover.verify", "module": "Handover", "label": "Verify handover", "description": "Verify parcel handover PINs."},
    {"key": "courier.assign", "module": "Handover", "label": "Assign courier deliveries", "description": "Assign a courier to a received doorstep parcel."},
    {"key": "exceptions.view", "module": "Exceptions", "label": "View exceptions", "description": "Review operational exceptions."},
    {"key": "exceptions.resolve", "module": "Exceptions", "label": "Resolve exceptions", "description": "Resolve reported operational exceptions."},
    {"key": "users.view", "module": "User management", "label": "View station users", "description": "List staff accounts within the assigned station scope."},
    {"key": "users.invite", "module": "User management", "label": "Invite station users", "description": "Invite staff and supervisors for the assigned station."},
    {"key": "users.manage", "module": "User management", "label": "Manage station users", "description": "Change role, station assignment and active access."},
    {"key": "reports.export", "module": "Reports", "label": "Export reports", "description": "Download authorized operational CSV reports."},
    {"key": "stations.view", "module": "Stations", "label": "View stations", "description": "View the active station directory."},
]

DEFAULT_ROLE_PERMISSIONS = {
    "admin": ["parcels.view", "parcels.create", "parcels.update", "parcels.receipt", "trips.view", "trips.manage", "receiving.scan", "handover.verify", "courier.assign", "exceptions.view", "exceptions.resolve", "users.view", "users.invite", "users.manage", "reports.export", "stations.view"],
    "supervisor": ["parcels.view", "parcels.create", "parcels.update", "parcels.receipt", "trips.view", "trips.manage", "receiving.scan", "handover.verify", "courier.assign", "exceptions.view", "exceptions.resolve", "reports.export", "stations.view"],
    "staff": ["parcels.view", "parcels.create", "parcels.receipt", "trips.view", "trips.manage", "receiving.scan", "handover.verify", "courier.assign", "exceptions.view", "reports.export", "stations.view"],
    "courier": ["parcels.view_assigned", "trips.view", "handover.verify", "stations.view"],
}
