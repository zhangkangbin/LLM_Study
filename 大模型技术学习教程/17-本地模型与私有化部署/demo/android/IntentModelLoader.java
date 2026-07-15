import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public final class IntentModelLoader {
    private static final int SCHEMA_VERSION = 1;
    private static final String ALGORITHM = "multinomial_naive_bayes";
    private static final String NORMALIZATION_STRATEGY =
            "whole_string_lower_then_alphanumeric_filter";
    private static final Pattern LABEL_PATTERN = Pattern.compile(
            "[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
    );
    private static final Pattern SHA256_PATTERN = Pattern.compile("[0-9a-f]{64}");
    private static final Set<String> ROOT_KEYS = Set.of(
            "schema_version",
            "model_version",
            "algorithm",
            "normalization",
            "labels",
            "thresholds",
            "statistics",
            "training_metadata",
            "evaluation_summary"
    );

    private IntentModelLoader() {}

    public record Thresholds(
            double confidence,
            double margin,
            double minimumAcceptedAccuracy
    ) {}

    public record IntentModel(
            int schemaVersion,
            String modelVersion,
            List<String> labels,
            Thresholds thresholds,
            Map<String, Integer> classCounts,
            Map<String, Map<String, Integer>> featureCounts,
            Map<String, Integer> totalFeatures,
            Set<String> vocabulary
    ) {
        public IntentModel {
            labels = List.copyOf(labels);
            classCounts = Map.copyOf(classCounts);
            totalFeatures = Map.copyOf(totalFeatures);
            Map<String, Map<String, Integer>> copiedFeatureCounts = new LinkedHashMap<>();
            for (Map.Entry<String, Map<String, Integer>> entry : featureCounts.entrySet()) {
                copiedFeatureCounts.put(entry.getKey(), Map.copyOf(entry.getValue()));
            }
            featureCounts = Map.copyOf(copiedFeatureCounts);
            vocabulary = Set.copyOf(vocabulary);
        }
    }

    public static IntentModel load(Path path) throws IOException {
        if (path == null) {
            throw new IllegalArgumentException("model path must not be null");
        }
        Object root = MiniJson.parse(Files.readString(path, StandardCharsets.UTF_8));
        return validateAndConvert(root);
    }

    private static IntentModel validateAndConvert(Object value) {
        Map<String, Object> root = requireObject("artifact", value);
        requireExactKeys("artifact", root, ROOT_KEYS);

        int schemaVersion = requireInteger("schema_version", root.get("schema_version"), 1);
        if (schemaVersion != SCHEMA_VERSION) {
            throw invalid("schema_version must be " + SCHEMA_VERSION);
        }
        String modelVersion = requireNonBlankString("model_version", root.get("model_version"));
        String algorithm = requireString("algorithm", root.get("algorithm"));
        if (!ALGORITHM.equals(algorithm)) {
            throw invalid("algorithm must be " + ALGORITHM);
        }

        validateNormalization(root.get("normalization"));
        List<String> labels = validateLabels(root.get("labels"));
        Thresholds thresholds = validateThresholds(root.get("thresholds"));
        Statistics statistics = validateStatistics(root.get("statistics"), labels);
        Map<String, Integer> splitCounts = validateTrainingMetadata(
                root.get("training_metadata"),
                sumCounts(statistics.classCounts())
        );
        validateEvaluationSummary(
                root.get("evaluation_summary"),
                splitCounts,
                thresholds.minimumAcceptedAccuracy()
        );

        return new IntentModel(
                schemaVersion,
                modelVersion,
                labels,
                thresholds,
                statistics.classCounts(),
                statistics.featureCounts(),
                statistics.totalFeatures(),
                statistics.vocabulary()
        );
    }

    private static void validateNormalization(Object value) {
        Map<String, Object> normalization = requireObject("normalization", value);
        requireExactKeys(
                "normalization",
                normalization,
                Set.of("version", "strategy", "ngram_range")
        );
        int version = requireInteger("normalization.version", normalization.get("version"), 0);
        if (version != 1) {
            throw invalid("normalization.version must be 1");
        }
        String strategy = requireString(
                "normalization.strategy",
                normalization.get("strategy")
        );
        if (!NORMALIZATION_STRATEGY.equals(strategy)) {
            throw invalid("unsupported normalization.strategy");
        }
        List<?> ngramRange = requireList(
                "normalization.ngram_range",
                normalization.get("ngram_range")
        );
        if (ngramRange.size() != 2
                || requireInteger("normalization.ngram_range[0]", ngramRange.get(0), 0) != 1
                || requireInteger("normalization.ngram_range[1]", ngramRange.get(1), 0) != 2) {
            throw invalid("normalization.ngram_range must be [1, 2]");
        }
    }

    private static List<String> validateLabels(Object value) {
        List<?> rawLabels = requireList("labels", value);
        if (rawLabels.isEmpty()) {
            throw invalid("labels must be a non-empty list");
        }
        List<String> labels = new ArrayList<>(rawLabels.size());
        String previous = null;
        for (int index = 0; index < rawLabels.size(); index++) {
            String label = requireNonBlankString("labels[" + index + "]", rawLabels.get(index));
            if (!LABEL_PATTERN.matcher(label).matches() || label.equals("unknown")) {
                throw invalid("labels must contain lower-snake-case intents other than unknown");
            }
            if (previous != null && previous.compareTo(label) >= 0) {
                throw invalid("labels must be unique and sorted");
            }
            labels.add(label);
            previous = label;
        }
        return List.copyOf(labels);
    }

    private static Thresholds validateThresholds(Object value) {
        Map<String, Object> thresholds = requireObject("thresholds", value);
        requireExactKeys(
                "thresholds",
                thresholds,
                Set.of("confidence", "margin", "minimum_accepted_accuracy")
        );
        return new Thresholds(
                requireThreshold("thresholds.confidence", thresholds.get("confidence")),
                requireThreshold("thresholds.margin", thresholds.get("margin")),
                requireThreshold(
                        "thresholds.minimum_accepted_accuracy",
                        thresholds.get("minimum_accepted_accuracy")
                )
        );
    }

    private static Statistics validateStatistics(Object value, List<String> labels) {
        Map<String, Object> statistics = requireObject("statistics", value);
        requireExactKeys(
                "statistics",
                statistics,
                Set.of("class_counts", "feature_counts", "total_features", "vocabulary")
        );
        Set<String> labelKeys = Set.copyOf(labels);
        Map<String, Object> rawClassCounts = requireObject(
                "statistics.class_counts",
                statistics.get("class_counts")
        );
        Map<String, Object> rawFeatureCounts = requireObject(
                "statistics.feature_counts",
                statistics.get("feature_counts")
        );
        Map<String, Object> rawTotalFeatures = requireObject(
                "statistics.total_features",
                statistics.get("total_features")
        );
        requireExactKeys("statistics.class_counts", rawClassCounts, labelKeys);
        requireExactKeys("statistics.feature_counts", rawFeatureCounts, labelKeys);
        requireExactKeys("statistics.total_features", rawTotalFeatures, labelKeys);

        Map<String, Integer> classCounts = new LinkedHashMap<>();
        Map<String, Integer> totalFeatures = new LinkedHashMap<>();
        Map<String, Map<String, Integer>> featureCounts = new LinkedHashMap<>();
        Set<String> featureUnion = new HashSet<>();

        for (String label : labels) {
            int classCount = requireInteger(
                    "statistics.class_counts." + label,
                    rawClassCounts.get(label),
                    1
            );
            int total = requireInteger(
                    "statistics.total_features." + label,
                    rawTotalFeatures.get(label),
                    0
            );
            if (total < classCount) {
                throw invalid(
                        "statistics.total_features." + label + " must be at least class_count"
                );
            }

            Map<String, Object> rawCounts = requireObject(
                    "statistics.feature_counts." + label,
                    rawFeatureCounts.get(label)
            );
            Map<String, Integer> counts = new LinkedHashMap<>();
            long calculatedTotal = 0;
            for (Map.Entry<String, Object> entry : rawCounts.entrySet()) {
                String feature = entry.getKey();
                validateFeature("statistics.feature_counts." + label, feature);
                int count = requireInteger(
                        "statistics.feature_counts." + label + "." + feature,
                        entry.getValue(),
                        1
                );
                calculatedTotal += count;
                counts.put(feature, count);
                featureUnion.add(feature);
            }
            if (calculatedTotal != total) {
                throw invalid("statistics.total_features." + label + " is inconsistent");
            }
            classCounts.put(label, classCount);
            totalFeatures.put(label, total);
            featureCounts.put(label, Map.copyOf(counts));
        }

        List<?> rawVocabulary = requireList(
                "statistics.vocabulary",
                statistics.get("vocabulary")
        );
        List<String> vocabulary = new ArrayList<>(rawVocabulary.size());
        String previous = null;
        for (int index = 0; index < rawVocabulary.size(); index++) {
            String feature = requireNonBlankString(
                    "statistics.vocabulary[" + index + "]",
                    rawVocabulary.get(index)
            );
            validateFeature("statistics.vocabulary[" + index + "]", feature);
            if (previous != null && compareByCodePoint(previous, feature) >= 0) {
                throw invalid("statistics.vocabulary must be unique and sorted");
            }
            vocabulary.add(feature);
            previous = feature;
        }
        Set<String> vocabularySet = Set.copyOf(vocabulary);
        if (!vocabularySet.equals(featureUnion)) {
            throw invalid("statistics.vocabulary must match the feature union");
        }
        return new Statistics(
                Map.copyOf(classCounts),
                Map.copyOf(featureCounts),
                Map.copyOf(totalFeatures),
                vocabularySet
        );
    }

    private static Map<String, Integer> validateTrainingMetadata(
            Object value,
            int totalTrainingExamples
    ) {
        Map<String, Object> metadata = requireObject("training_metadata", value);
        requireExactKeys(
                "training_metadata",
                metadata,
                Set.of("trained_at", "split_counts", "dataset_sha256")
        );
        String trainedAt = requireString("training_metadata.trained_at", metadata.get("trained_at"));
        if (!trainedAt.endsWith("Z")) {
            throw invalid("training_metadata.trained_at must be a UTC ISO-8601 timestamp");
        }
        try {
            Instant.parse(trainedAt);
        } catch (DateTimeParseException error) {
            throw invalid("training_metadata.trained_at must be a UTC ISO-8601 timestamp");
        }
        String fingerprint = requireString(
                "training_metadata.dataset_sha256",
                metadata.get("dataset_sha256")
        );
        if (!SHA256_PATTERN.matcher(fingerprint).matches()) {
            throw invalid("training_metadata.dataset_sha256 must be lowercase SHA-256");
        }
        Map<String, Object> rawSplitCounts = requireObject(
                "training_metadata.split_counts",
                metadata.get("split_counts")
        );
        requireExactKeys(
                "training_metadata.split_counts",
                rawSplitCounts,
                Set.of("train", "validation", "test")
        );
        Map<String, Integer> splitCounts = new LinkedHashMap<>();
        for (String split : List.of("train", "validation", "test")) {
            splitCounts.put(
                    split,
                    requireInteger(
                            "training_metadata.split_counts." + split,
                            rawSplitCounts.get(split),
                            1
                    )
            );
        }
        if (splitCounts.get("train") != totalTrainingExamples) {
            throw invalid("training_metadata train count is inconsistent");
        }
        return Map.copyOf(splitCounts);
    }

    private static void validateEvaluationSummary(
            Object value,
            Map<String, Integer> splitCounts,
            double minimumAcceptedAccuracy
    ) {
        Map<String, Object> summaries = requireObject("evaluation_summary", value);
        requireExactKeys("evaluation_summary", summaries, Set.of("validation", "test"));
        Set<String> summaryKeys = Set.of(
                "count",
                "accuracy",
                "macro",
                "rejection_rate",
                "coverage",
                "accepted_accuracy"
        );
        for (String split : List.of("validation", "test")) {
            String path = "evaluation_summary." + split;
            Map<String, Object> summary = requireObject(path, summaries.get(split));
            requireExactKeys(path, summary, summaryKeys);
            int count = requireInteger(path + ".count", summary.get("count"), 0);
            if (count != splitCounts.get(split)) {
                throw invalid(path + ".count is inconsistent");
            }
            double accuracy = requireThreshold(path + ".accuracy", summary.get("accuracy"));
            double rejectionRate = requireThreshold(
                    path + ".rejection_rate",
                    summary.get("rejection_rate")
            );
            double coverage = requireThreshold(path + ".coverage", summary.get("coverage"));
            double acceptedAccuracy = requireThreshold(
                    path + ".accepted_accuracy",
                    summary.get("accepted_accuracy")
            );
            int correctCount = ratioCount(path + ".accuracy", accuracy, count);
            int acceptedCount = ratioCount(path + ".coverage", coverage, count);
            int rejectedCount = ratioCount(path + ".rejection_rate", rejectionRate, count);
            if (Math.abs(coverage + rejectionRate - 1.0) > 1e-12
                    || acceptedCount + rejectedCount != count) {
                throw invalid(path + " coverage and rejection_rate are inconsistent");
            }
            int acceptedCorrect;
            if (acceptedCount == 0) {
                if (acceptedAccuracy != 0.0) {
                    throw invalid(path + ".accepted_accuracy must be 0 when coverage is 0");
                }
                acceptedCorrect = 0;
            } else {
                acceptedCorrect = ratioCount(
                        path + ".accepted_accuracy",
                        acceptedAccuracy,
                        acceptedCount
                );
            }
            if (acceptedCorrect > correctCount
                    || correctCount > acceptedCorrect + rejectedCount) {
                throw invalid(path + " correct counts are inconsistent");
            }
            if (split.equals("validation") && acceptedAccuracy < minimumAcceptedAccuracy) {
                throw invalid(
                        "evaluation_summary.validation.accepted_accuracy must satisfy "
                                + "thresholds.minimum_accepted_accuracy"
                );
            }
            Map<String, Object> macro = requireObject(path + ".macro", summary.get("macro"));
            requireExactKeys(path + ".macro", macro, Set.of("precision", "recall", "f1"));
            for (String metric : List.of("precision", "recall", "f1")) {
                requireThreshold(path + ".macro." + metric, macro.get(metric));
            }
        }
    }

    private static int ratioCount(String path, double ratio, int count) {
        double scaled = ratio * count;
        long nearest = Math.round(scaled);
        if (Math.abs(scaled - nearest) > 1e-9 || nearest > Integer.MAX_VALUE) {
            throw invalid(path + " is impossible for count " + count);
        }
        return (int) nearest;
    }

    private static int sumCounts(Map<String, Integer> counts) {
        long total = 0;
        for (int count : counts.values()) {
            total += count;
        }
        if (total > Integer.MAX_VALUE) {
            throw invalid("statistics.class_counts total exceeds the Java int range");
        }
        return (int) total;
    }

    private static void validateFeature(String path, String feature) {
        if (feature.isBlank()) {
            throw invalid(path + " contains a blank feature");
        }
        int codePoints = feature.codePointCount(0, feature.length());
        if ((codePoints != 1 && codePoints != 2) || !normalize(feature).equals(feature)) {
            throw invalid(
                    path + " features must be normalized one- or two-code-point n-grams"
            );
        }
    }

    private static String normalize(String value) {
        String lowered = value.toLowerCase(Locale.ROOT);
        StringBuilder normalized = new StringBuilder();
        lowered.codePoints()
                .filter(IntentModelLoader::isPythonAlphanumeric)
                .forEach(normalized::appendCodePoint);
        return normalized.toString();
    }

    static boolean isPythonAlphanumeric(int codePoint) {
        if (Character.isLetterOrDigit(codePoint)) {
            return true;
        }
        int type = Character.getType(codePoint);
        return type == Character.LETTER_NUMBER || type == Character.OTHER_NUMBER;
    }

    private static int compareByCodePoint(String left, String right) {
        int leftIndex = 0;
        int rightIndex = 0;
        while (leftIndex < left.length() && rightIndex < right.length()) {
            int leftCodePoint = left.codePointAt(leftIndex);
            int rightCodePoint = right.codePointAt(rightIndex);
            int comparison = Integer.compare(leftCodePoint, rightCodePoint);
            if (comparison != 0) {
                return comparison;
            }
            leftIndex += Character.charCount(leftCodePoint);
            rightIndex += Character.charCount(rightCodePoint);
        }
        return Integer.compare(left.length() - leftIndex, right.length() - rightIndex);
    }

    private static Map<String, Object> requireObject(String path, Object value) {
        if (!(value instanceof Map<?, ?> raw)) {
            throw invalid(path + " must be an object");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw invalid(path + " object keys must be strings");
            }
            result.put(key, entry.getValue());
        }
        return result;
    }

    private static List<?> requireList(String path, Object value) {
        if (!(value instanceof List<?> list)) {
            throw invalid(path + " must be an array");
        }
        return list;
    }

    private static String requireString(String path, Object value) {
        if (!(value instanceof String string)) {
            throw invalid(path + " must be a string");
        }
        return string;
    }

    private static String requireNonBlankString(String path, Object value) {
        String string = requireString(path, value);
        if (string.isBlank()) {
            throw invalid(path + " must be a non-blank string");
        }
        return string;
    }

    private static int requireInteger(String path, Object value, int minimum) {
        if (!(value instanceof Long integer)
                || integer < minimum
                || integer > Integer.MAX_VALUE) {
            String qualifier = minimum == 1 ? "positive" : "non-negative";
            throw invalid(path + " must be a " + qualifier + " JSON integer in Java int range");
        }
        return integer.intValue();
    }

    private static double requireThreshold(String path, Object value) {
        if (!(value instanceof Number number)) {
            throw invalid(path + " must be a finite number in [0, 1]");
        }
        double threshold = number.doubleValue();
        if (!Double.isFinite(threshold) || threshold < 0.0 || threshold > 1.0) {
            throw invalid(path + " must be a finite number in [0, 1]");
        }
        return threshold == 0.0 ? 0.0 : threshold;
    }

    private static void requireExactKeys(
            String path,
            Map<String, ?> object,
            Set<String> expected
    ) {
        if (!object.keySet().equals(expected)) {
            Set<String> missing = new HashSet<>(expected);
            missing.removeAll(object.keySet());
            Set<String> unexpected = new HashSet<>(object.keySet());
            unexpected.removeAll(expected);
            throw invalid(
                    path + " has invalid keys; missing=" + missing + ", unexpected=" + unexpected
            );
        }
    }

    private static IllegalArgumentException invalid(String message) {
        return new IllegalArgumentException("Invalid intent model artifact: " + message);
    }

    private record Statistics(
            Map<String, Integer> classCounts,
            Map<String, Map<String, Integer>> featureCounts,
            Map<String, Integer> totalFeatures,
            Set<String> vocabulary
    ) {}
}
