import SurveillanceMonitor from "../../components/SurveillanceMonitor";

export const metadata = {
  title: "AEGIS — Live Surveillance Monitor",
  description:
    "SOC-style live camera surveillance with real-time deepfake anomaly scoring, rolling score chart, multi-detector sub-scores, and alert escalation.",
};

export default function SurveillancePage() {
  return <SurveillanceMonitor />;
}
