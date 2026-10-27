from stocklock.shared.exceptions import StaticException


class NoActiveSession(StaticException):
  message = "No active session"


class SessionTaskMismatch(StaticException):
  message = "The active session belongs to another task"


class TransactionAlreadyActive(StaticException):
  message = "A transaction is already active"


class TransactionTaskRequired(StaticException):
  message = "A transaction requires an asyncio task"


class ConfirmationConflict(StaticException):
  message = "Confirmation conflict did not return an existing result"


class ServerTimeUnavailable(StaticException):
  message = "Unable to get time from server"


class EntityUpdateConflict(StaticException):
  message = "The locked entity was not found during persistence"
