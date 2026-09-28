{{- define "networkclaw-bundle.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "networkclaw-bundle.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "networkclaw-bundle.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "networkclaw-bundle.labels" -}}
app.kubernetes.io/name: {{ include "networkclaw-bundle.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: networkclaw-bundle
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "networkclaw-bundle.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "networkclaw-bundle.provenanceAnnotations" -}}
{{- with .Values.provenance.bundleSha256 }}networkclaw.io/bundle-sha256: {{ . | quote }}{{ end }}
{{- with .Values.provenance.networkclawCommit }}networkclaw.io/networkclaw-commit: {{ . | quote }}{{ end }}
{{- with .Values.provenance.harnessCommit }}networkclaw.io/harness-commit: {{ . | quote }}{{ end }}
{{- with .Values.provenance.integrationCommit }}networkclaw.io/integration-commit: {{ . | quote }}{{ end }}
{{- end -}}

{{- define "networkclaw-bundle.namespace" -}}
{{- default .Release.Namespace .Values.discovery.namespace -}}
{{- end -}}
