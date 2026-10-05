"""
Compatibility module mapping subscriptions.models to App.Subscriptions.sub_models
"""
from App.Subscriptions.sub_models import (
    Plan,
    Plan as SubscriptionPlan,
    Plan as StudioPlan,
    PhotographerSubscription,
    PhotographerSubscription as CurrentSubscription,
    PhotographerSubscription as UserSubscription,
    SubscriptionPlans,
    SubscriptionPayment,
)

__all__ = [
    'Plan',
    'SubscriptionPlan',
    'StudioPlan',
    'PhotographerSubscription',
    'CurrentSubscription',
    'UserSubscription',
    'SubscriptionPlans',
    'SubscriptionPayment',
]
