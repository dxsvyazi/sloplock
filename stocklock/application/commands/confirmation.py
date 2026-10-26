from dataclasses import dataclass

from stocklock.application.commands.reservation import GetReservationCommand


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmReservationCommand(GetReservationCommand):
  pass


@dataclass(frozen=True, slots=True, kw_only=True)
class GetConfirmationCommand(GetReservationCommand):
  pass
