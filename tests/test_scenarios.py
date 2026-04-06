import pytest
from backend.simulator.components import RACK_HOSTS
from backend.simulator.scenarios import (
    Scenario,
    gpu_hardware_failure,
    network_partition,
    pick_scenario,
    power_anomaly,
    storage_degradation,
    thermal_cascade,
)

VALID_SEVERITIES = {"info", "warning", "critical"}
ALL_GENERATORS = [
    ("thermal_cascade", thermal_cascade),
    ("gpu_hardware_failure", gpu_hardware_failure),
    ("network_partition", network_partition),
    ("storage_degradation", storage_degradation),
    ("power_anomaly", power_anomaly),
]


@pytest.mark.parametrize("name,gen", ALL_GENERATORS)
class TestScenarioStructure:
    def test_name(self, name, gen):
        scenario = gen()
        assert scenario.name == name

    def test_has_four_alerts(self, name, gen):
        scenario = gen()
        assert len(scenario.alerts) == 4

    def test_severity_values(self, name, gen):
        scenario = gen()
        for alert in scenario.alerts:
            assert alert.severity in VALID_SEVERITIES, (
                f"{name} alert has invalid severity: {alert.severity}"
            )

    def test_hosts_belong_to_racks(self, name, gen):
        scenario = gen()
        for alert in scenario.alerts:
            assert alert.rack in RACK_HOSTS, (
                f"{name} alert references unknown rack: {alert.rack}"
            )
            assert alert.host in RACK_HOSTS[alert.rack], (
                f"{name}: host {alert.host} not in {alert.rack}"
            )


def test_pick_scenario_returns_valid():
    scenario = pick_scenario()
    assert isinstance(scenario, Scenario)
    assert scenario.name
    assert len(scenario.alerts) > 0
