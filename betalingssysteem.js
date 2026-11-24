// Reference values for the server-side subscription and storage rules.
export const BILLING_CONFIG = {
  monthlyPriceEUR: 20,
  paidStorageLimitGB: 100,
  churches: {
    "ministere-apostolique-impact": {
      name: "Ministère Apostolique Impact",
      adminEmail: "kaat.dbolle@gmail.com",
      plan: "free",
      subscriptionStatus: "active",
      stripeCustomerId: null,
      stripeSubscriptionId: null,
      storageLimitGB: null,
    },
  },
};
