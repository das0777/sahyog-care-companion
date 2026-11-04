"""The only way a message may leave for a patient's phone.

No SMS or call adapter exists in this build: the outbox rows are a stub. Any adapter added later
sends through `deliver`, which refuses synthetic patients. Seed phones use +91 55, which is outside
India's mobile ranges but can match a real landline, so this rule is what protects real people.
"""

from sahyog.models import Patient, SmsOutbox


class SyntheticRecipient(RuntimeError):
    """A message was addressed to a synthetic patient."""


class NoSender(RuntimeError):
    """No SMS adapter is configured."""


def deliver(sms: SmsOutbox, patient: Patient, sender=None) -> None:
    if patient.patient_id != sms.patient_id:
        raise ValueError("message and patient don't match")
    if patient.synthetic:
        raise SyntheticRecipient(f"{patient.patient_id} is synthetic and is never contacted")
    if sender is None:
        raise NoSender("no SMS adapter is configured")
    sender.send(patient.phone, sms.template, sms.vars)
