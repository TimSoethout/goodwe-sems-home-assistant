# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [8.1.0-beta] - Unreleased

### Breaking Changes

#### Switch Device Class Change

The inverter control switch device class has been changed from `OUTLET` to `SWITCH` to better reflect its actual purpose (controlling an inverter, not an electrical outlet).

**Impact:**
- Users with automations or dashboards that reference the switch's device class may need to update their configurations
- The entity ID and functionality remain unchanged - only the device class metadata has changed
- This affects how the switch appears in the Home Assistant UI and which categories it appears under

**Migration:**
- If you have automations that filter by device class `outlet`, update them to use device class `switch`
- If you have UI cards or dashboards that display entities by device class, you may need to adjust the filters
- Most users will not need to take any action as entity IDs remain the same

### Added
- Separate entities for different sensor types (power, energy, status, etc.)
- New status sensor for inverter status monitoring
- Improved entity naming with `has_entity_name` attribute

### Changed
- Switch device class changed from `OUTLET` to `SWITCH`
- Refactored entity structure for better organization
- Improved backwards compatibility for power sensor attributes

### Fixed
- Entity ID consistency issues
- Restored `extra_state_attributes` on power sensor for backwards compatibility
