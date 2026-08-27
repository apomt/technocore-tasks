import { defineRailway, github, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const data = volume("technocore-tasks-volume", {
    region: "ams",
    sizeMB: 5000,
  });

  const web = service("technocore-tasks", {
    source: github("apomt/technocore-tasks", { branch: "main" }),
    start: "python -m technocore_tasks serve",
    healthcheck: "/health",
    healthcheckTimeout: 20,
    replicas: 1,
    env: {
      TASKS_MODE: "hosted",
      TASKS_DATABASE: "/data/technocore_tasks.db",
      TASKS_SOURCE_ROOMS: "kibble",
      TASKS_COLLECTOR_ENABLED: "1",
      TECHNOCORE_BASE_URL: "https://technocore.chat",
    },
    volumeMounts: {
      "/data": data,
    },
  });

  return project("technocore-tasks", {
    resources: [web, data],
  });
});
