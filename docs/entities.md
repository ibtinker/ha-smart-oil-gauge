# Tank entities

Entity IDs are examples; actual IDs depend on your Home Assistant configuration. Return to the [README](../README.md) for setup.

## Entities

| Entity Name | Entity ID | Description |
| :--- | :--- | :--- |
| **Oil Level** | `sensor.oil_tank_level` | Remaining fuel level in gallons (physical sensor reading or model estimate). |
| **Oil Percentage** | `sensor.oil_tank_percentage` | Percentage of total tank capacity remaining. |
| **Daily Usage Rate** | `sensor.oil_tank_daily_usage_rate` | Rolling average daily fuel consumption (`gal/day`). |
| **Estimated Runout Date** | `sensor.oil_tank_estimated_runout_date` | Estimated date when fuel reaches 0 gallons based on current usage. |
| **Last Refill Amount** | `sensor.oil_tank_last_refill_amount` | Gallons added during the most recent detected refill. Attribute `equalizing` ("Refill equalization in progress") is `true` while the level is still rising after a delivery. A delivery itself takes minutes; a level that keeps climbing for hours afterwards is a second tank equalizing through its connecting line, or the oil settling. The amount keeps updating until the level levels off. |
| **Last Refill Date** | `sensor.oil_tank_last_refill_date` | Date and time when the last refill occurred. |
| **Max Level** | `sensor.oil_tank_max_level` | Total nominal tank capacity in gallons. |
| **Max Fill** | `sensor.oil_tank_max_fill` | Remaining fillable tank capacity in gallons. |
| **Days to 1/4** | `sensor.oil_tank_days_to_1_4` | Estimated days remaining until fuel reaches 25% capacity. |
| **Days to 1/8** | `sensor.oil_tank_days_to_1_8` | Estimated days remaining until fuel reaches 12.5% capacity. |
| **Battery** | `sensor.oil_tank_battery` | Battery health status (`Excellent`, `Good`, `Fair`, `Poor`). |
| **Last Portal Sync** | `sensor.oil_tank_last_portal_sync` | When Home Assistant last synced with the portal successfully. (Renamed from "Last Portal Update"; existing installs keep their `..._last_portal_update` entity ID.) |
| **Last Gauge Upload** | `sensor.oil_tank_last_gauge_upload` | When the gauge last uploaded its readings to the portal. |
| **Next Gauge Upload** | `sensor.oil_tank_next_gauge_upload` | When the gauge should next upload (last upload + its upload interval). Attributes: `next_sync` (when the integration will check the portal) and `overdue`. |
| **Upload Interval In Use** | `sensor.oil_tank_upload_interval_in_use` | The upload interval (hours) the gauge is using now, which sets when the next upload is expected. Differs from the Upload interval select while a change is pending. Attributes: `portal_interval_hours`, `pending`, `source` (`portal` or `measured`). |
| **Upload Interval Change Pending** | `binary_sensor.oil_tank_upload_interval_change_pending` | On while a new upload interval waits for the gauge's next upload (the gauge only fetches its settings when it uploads). Attributes: `portal_interval_hours`, `gauge_interval_hours`. |
| **Sync Now** (button) | `button.oil_tank_sync_now` | Checks the portal for new readings immediately. |
| **Upload Interval** (select) | `select.oil_tank_upload_interval` | The gauge's upload interval (hours) as set on the portal. Changing it updates the portal; the gauge picks it up at its next upload. Attributes: `effective_interval_hours` (in use now), `pending`, `interval_source` (`portal` or `measured`), `number_of_tanks`. |
| **Import History** (button) | `button.oil_tank_import_history` | Downloads the gauge's full hourly history from the portal and adds it to Home Assistant's history and statistics. Safe to press again. |
| **Low Fuel Alert** | `binary_sensor.oil_tank_low_fuel_alert` | Alert triggered when fuel level drops below the low threshold. |
