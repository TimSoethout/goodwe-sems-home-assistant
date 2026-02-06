"""Simple integration tests for the SEMS API module using requests_mock."""

from custom_components.sems.sems_api import SemsApi

# Anonymized data constants for testing
MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"
MOCK_INVERTER_SN = "GW0000SN000TEST1"


class TestSemsApiSimple:
    """Simple test class for SemsApi with real JSON fixtures."""

    def setup_method(self):
        """Set up test fixtures."""
        self.username = "test_user"
        self.password = "test_password"
        self.api = SemsApi(None, self.username, self.password)

    def test_initialization(self):
        """Test SemsApi initialization."""
        # Test basic initialization without accessing private members
        assert self.api is not None

    def test_successful_login(self, requests_mock):
        """Test successful login with realistic response."""
        login_response = {
            "hasError": False,
            "code": 0,
            "msg": "操作成功",
            "data": {"uid": "test-uid-123", "token": "test-token-abc123"},
            "api": "https://eu.semsportal.com/api/",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is not None
        assert result["uid"] == "test-uid-123"
        assert result["token"] == "test-token-abc123"
        assert result["api"] == "https://eu.semsportal.com/api/"

    def test_failed_login_invalid_credentials(self, requests_mock):
        """Test failed login with invalid credentials."""
        login_response = {
            "hasError": True,
            "code": 1001,
            "msg": "Invalid credentials",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.getLoginToken(self.username, self.password)

        assert result is None

    def test_authentication_success(self, requests_mock):
        """Test successful authentication."""
        login_response = {
            "hasError": False,
            "code": 0,
            "msg": "操作成功",
            "data": {"uid": "test-uid-123", "token": "test-token-abc123"},
            "api": "https://eu.semsportal.com/api/",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        result = self.api.test_authentication()

        assert result is True

    def test_get_power_station_ids_success(self, requests_mock):
        """Test successful retrieval of power station IDs."""
        # Mock login
        login_response = {
            "hasError": False,
            "code": 0,
            "msg": "操作成功",
            "data": {"uid": "test-uid-123", "token": "test-token-abc123"},
            "api": "https://eu.semsportal.com/api/",
        }

        requests_mock.post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin", json=login_response
        )

        # Mock power station IDs response with real structure
        power_station_response = {
            "hasError": False,
            "code": 0,
            "msg": "操作成功",
            "data": MOCK_POWER_STATION_ID,
        }

        requests_mock.post(
            "https://eu.semsportal.com/api//PowerStation/GetPowerStationIdByOwner",
            json=power_station_response,
        )

        result = self.api.getPowerStationId()

        assert result is not None
        assert result == MOCK_POWER_STATION_ID

    def test_constants_available(self):
        """Test that anonymized test constants are available."""
        assert MOCK_POWER_STATION_ID == "12345678-1234-5678-9abc-123456789abc"
        assert MOCK_INVERTER_SN == "GW0000SN000TEST1"
