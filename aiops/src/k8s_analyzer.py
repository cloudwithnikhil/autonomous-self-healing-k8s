from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KubernetesAnalyzer:
    def __init__(self):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        # Local Docker + Kind only.
        #
        # The Kind API certificate is issued for 127.0.0.1, while
        # Docker reaches the Windows host through host.docker.internal.
        # Disable hostname verification for this local development setup.
        configuration = client.Configuration.get_default_copy()
        configuration.verify_ssl = False

        client.Configuration.set_default(configuration)

        self.apps_api = client.AppsV1Api()
        self.core_api = client.CoreV1Api()

    def get_deployment_state(
        self,
        namespace: str,
        deployment_name: str,
    ):
        try:
            deployment = self.apps_api.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
            )

            spec = deployment.spec
            status = deployment.status

            container = spec.template.spec.containers[0]

            return {
                "deployment": deployment.metadata.name,
                "namespace": namespace,
                "desired_replicas": spec.replicas or 0,
                "available_replicas": status.available_replicas or 0,
                "ready_replicas": status.ready_replicas or 0,
                "updated_replicas": status.updated_replicas or 0,
                "image": container.image,
                "generation": deployment.metadata.generation,
                "observed_generation": status.observed_generation,
            }

        except ApiException as exc:
            raise RuntimeError(
                f"Failed to read deployment "
                f"{namespace}/{deployment_name}: {exc}"
            )

    def get_pod_states(
        self,
        namespace: str,
        label_selector: str,
    ):
        try:
            pods = self.core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
            )

            results = []

            for pod in pods.items:
                restart_count = 0
                container_states = []

                if pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        restart_count += container_status.restart_count

                        state = container_status.state

                        if state:
                            if state.running:
                                container_state = "running"
                            elif state.waiting:
                                container_state = "waiting"
                            elif state.terminated:
                                container_state = "terminated"
                            else:
                                container_state = "unknown"
                        else:
                            container_state = "unknown"

                        container_states.append(
                            {
                                "name": container_status.name,
                                "ready": container_status.ready,
                                "restart_count": container_status.restart_count,
                                "state": container_state,
                            }
                        )

                results.append(
                    {
                        "name": pod.metadata.name,
                        "phase": pod.status.phase,
                        "restart_count": restart_count,
                        "containers": container_states,
                    }
                )

            return results

        except ApiException as exc:
            raise RuntimeError(
                f"Failed to read pods in namespace "
                f"{namespace}: {exc}"
            )

    def analyze(
        self,
        namespace: str,
        deployment_name: str,
        label_selector: str,
    ):
        deployment = self.get_deployment_state(
            namespace=namespace,
            deployment_name=deployment_name,
        )

        pods = self.get_pod_states(
            namespace=namespace,
            label_selector=label_selector,
        )

        total_restarts = sum(
            pod["restart_count"]
            for pod in pods
        )

        running_pods = sum(
            1
            for pod in pods
            if pod["phase"] == "Running"
        )

        return {
            "deployment": deployment,
            "pods": pods,
            "summary": {
                "pod_count": len(pods),
                "running_pods": running_pods,
                "total_restarts": total_restarts,
            },
        }