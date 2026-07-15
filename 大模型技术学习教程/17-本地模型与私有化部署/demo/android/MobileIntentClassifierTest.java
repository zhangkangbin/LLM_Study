import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public final class MobileIntentClassifierTest {
    private MobileIntentClassifierTest() {}

    public static void main(String[] args) throws Exception {
        require(args.length == 1 || args.length == 2, "expected model path and optional Unicode model path");
        Path modelPath = Path.of(args[0]);
        String artifact = Files.readString(modelPath, StandardCharsets.UTF_8);
        List<Path> temporaryArtifacts = new ArrayList<>();

        try {
            testMiniJson();
            testPythonAlphanumericCategories();
            testValidArtifact(modelPath);
            if (args.length == 2) {
                testPythonAlphanumericArtifact(Path.of(args[1]));
            }
            testCorruptArtifacts(artifact, temporaryArtifacts);
            System.out.println("MobileIntentClassifierTest OK");
        } finally {
            for (Path path : temporaryArtifacts) {
                Files.deleteIfExists(path);
            }
        }
    }

    private static void testMiniJson() {
        Object parsed = MiniJson.parse(
                "{\"array\":[null,true,false,-12,3.5,6e2],"
                        + "\"escaped\":\"line\\nquote\\\"slash\\\\tab\\t\"}"
        );
        require(parsed instanceof Map<?, ?>, "JSON object type");
        Map<?, ?> object = (Map<?, ?>) parsed;
        require(object.get("array") instanceof List<?>, "JSON array type");
        List<?> array = (List<?>) object.get("array");
        require(array.size() == 6, "JSON array size");
        require(array.get(0) == null, "JSON null");
        require(Boolean.TRUE.equals(array.get(1)), "JSON true");
        require(Boolean.FALSE.equals(array.get(2)), "JSON false");
        require(Long.valueOf(-12).equals(array.get(3)), "JSON integer");
        require(Double.valueOf(3.5).equals(array.get(4)), "JSON fraction");
        require(Double.valueOf(600.0).equals(array.get(5)), "JSON exponent");
        require(
                "line\nquote\"slash\\tab\t".equals(object.get("escaped")),
                "JSON escapes"
        );

        String grinningFace = new String(Character.toChars(0x1F600));
        require(
                grinningFace.equals(MiniJson.parse("\"\\uD83D\\uDE00\"")),
                "escaped surrogate pair"
        );
        require(
                grinningFace.equals(MiniJson.parse("\"" + grinningFace + "\"")),
                "raw supplementary code point"
        );

        expectParseError("{\"a\":1,\"a\":2}");
        expectParseError("true false");
        expectParseError("\"\\x\"");
        expectParseError("\"\\u00G0\"");
        expectParseError("\"control" + String.valueOf((char) 1) + "\"");
        expectParseError("01");
        expectParseError("+1");
        expectParseError("-");
        expectParseError("1.");
        expectParseError(".1");
        expectParseError("1e");
        expectParseError("1e+");
        expectParseError("NaN");
        expectParseError("Infinity");
        expectParseError("1e309");
        expectParseError("\"\\u１２３４\"");
        expectParseError("\"\\uD800\"");
        expectParseError("\"\\uDC00\"");
        expectParseError("\"\\uD800x\"");
    }

    private static void testValidArtifact(Path modelPath) throws IOException {
        IntentModelLoader.IntentModel model = IntentModelLoader.load(modelPath);
        require(model.schemaVersion() == 1, "schema version");
        require(!model.modelVersion().isBlank(), "model version");
        require(model.labels().contains("cancel_order"), "cancel_order label");
        require(model.labels().size() >= 2, "multiple labels");
        require(model.thresholds().confidence() >= 0.0, "confidence threshold");
        require(model.thresholds().margin() >= 0.0, "margin threshold");
        require(
                model.thresholds().minimumAcceptedAccuracy() >= 0.0,
                "minimum accepted accuracy"
        );
        require(
                model.classCounts().keySet().equals(model.featureCounts().keySet()),
                "feature count labels"
        );
        require(
                model.classCounts().keySet().equals(model.totalFeatures().keySet()),
                "total feature labels"
        );
        require(!model.vocabulary().isEmpty(), "vocabulary");

        String firstLabel = model.labels().get(0);
        expectUnsupported(() -> model.labels().add("other"));
        expectUnsupported(() -> model.classCounts().put(firstLabel, 99));
        expectUnsupported(() -> model.totalFeatures().clear());
        expectUnsupported(() -> model.featureCounts().clear());
        expectUnsupported(() -> model.featureCounts().get(firstLabel).clear());
        expectUnsupported(() -> model.vocabulary().clear());
    }

    private static void testPythonAlphanumericCategories() {
        require(Character.getType('²') == Character.OTHER_NUMBER, "No category evidence");
        require(Character.getType('ⅷ') == Character.LETTER_NUMBER, "Nl category evidence");
        require(IntentModelLoader.isPythonAlphanumeric('a'), "Python alphabetic character");
        require(IntentModelLoader.isPythonAlphanumeric('²'), "Python No character");
        require(IntentModelLoader.isPythonAlphanumeric('ⅷ'), "Python Nl character");
        require(!IntentModelLoader.isPythonAlphanumeric('☃'), "non-alphanumeric symbol");
    }

    private static void testPythonAlphanumericArtifact(Path modelPath) throws IOException {
        IntentModelLoader.IntentModel model = IntentModelLoader.load(modelPath);
        require(model.labels().equals(List.of("number_intent")), "Unicode model label");
        require(model.vocabulary().contains("²"), "Python No feature");
        require(model.vocabulary().contains("ⅷ"), "Python Nl feature");
        require(model.vocabulary().contains("²ⅷ"), "Python No/Nl bigram feature");
    }

    private static void testCorruptArtifacts(
            String artifact,
            List<Path> temporaryArtifacts
    ) throws IOException {
        expectInvalidArtifact("{}", temporaryArtifacts);
        expectInvalidArtifact(
                insertTopLevelMember(artifact, "\"unexpected\":true"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "schema_version", "2"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "schema_version", "1.0"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "algorithm", "\"other\""),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "normalization", "[]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "normalization",
                        "{\"version\":2,\"strategy\":"
                                + "\"whole_string_lower_then_alphanumeric_filter\","
                                + "\"ngram_range\":[1,2]}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "normalization",
                        "{\"version\":1,\"strategy\":\"other\","
                                + "\"ngram_range\":[1,2]}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "normalization",
                        "{\"version\":1,\"strategy\":"
                                + "\"whole_string_lower_then_alphanumeric_filter\","
                                + "\"ngram_range\":[1,3]}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "labels", "[\"cancel_order\",\"cancel_order\"]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "labels", "[\"unknown\"]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "labels",
                        "[\"human_service\",\"cancel_order\"]"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "thresholds",
                        "{\"confidence\":1.1,\"margin\":0.0,"
                                + "\"minimum_accepted_accuracy\":0.75}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "thresholds",
                        "{\"confidence\":0.0,\"margin\":-0.1,"
                                + "\"minimum_accepted_accuracy\":0.75}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(
                        artifact,
                        "thresholds",
                        "{\"confidence\":0.0,\"margin\":0.0,"
                                + "\"minimum_accepted_accuracy\":2}"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(artifact, "class_counts", "0", false),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(artifact, "class_counts", "-1", false),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(artifact, "class_counts", "1.0", false),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(
                        artifact,
                        "class_counts",
                        "2147483648",
                        false
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(artifact, "feature_counts", "0", true),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(artifact, "total_features", "0", false),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectNumber(
                        artifact,
                        "total_features",
                        "2147483647",
                        false
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstFeatureName(artifact, "A"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstFeatureName(artifact, "☃"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceFirstObjectKey(
                        artifact,
                        "class_counts",
                        "external_label"
                ),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "vocabulary", "[]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                duplicateFirstArrayString(artifact, "vocabulary"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "training_metadata", "[]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "training_metadata", "{}"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "evaluation_summary", "[]"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                insertTopLevelMember(artifact, "\"schema_version\":1"),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "model_version", "\"\\uD800\""),
                temporaryArtifacts
        );
        expectInvalidArtifact(
                replaceJsonValue(artifact, "schema_version", "01"),
                temporaryArtifacts
        );
    }

    private static void expectParseError(String source) {
        try {
            MiniJson.parse(source);
            throw new AssertionError("expected JSON parse failure: " + source);
        } catch (IllegalArgumentException error) {
            require(error.getMessage().contains("position"), "JSON error position");
        }
    }

    private static void expectInvalidArtifact(
            String source,
            List<Path> temporaryArtifacts
    ) throws IOException {
        Path path = Files.createTempFile("invalid-intent-model-", ".json");
        temporaryArtifacts.add(path);
        Files.writeString(path, source, StandardCharsets.UTF_8);
        try {
            IntentModelLoader.load(path);
            throw new AssertionError("expected invalid artifact: " + path);
        } catch (IllegalArgumentException expected) {
            require(
                    expected.getMessage() != null && !expected.getMessage().isBlank(),
                    "artifact error message"
            );
        }
    }

    private static String insertTopLevelMember(String source, String member) {
        require(source.charAt(0) == '{', "artifact object start");
        return "{" + member + "," + source.substring(1);
    }

    private static String replaceJsonValue(
            String source,
            String key,
            String replacement
    ) {
        String quotedKey = "\"" + key + "\"";
        int keyStart = source.indexOf(quotedKey);
        require(keyStart >= 0, "missing JSON key: " + key);
        int colon = skipWhitespace(source, keyStart + quotedKey.length());
        require(colon < source.length() && source.charAt(colon) == ':', "key colon");
        int valueStart = skipWhitespace(source, colon + 1);
        int valueEnd = findJsonValueEnd(source, valueStart);
        return source.substring(0, valueStart) + replacement + source.substring(valueEnd);
    }

    private static String replaceFirstObjectNumber(
            String source,
            String objectKey,
            String replacement,
            boolean nested
    ) {
        int marker = source.indexOf("\"" + objectKey + "\"");
        require(marker >= 0, "missing object: " + objectKey);
        int objectStart = source.indexOf('{', marker);
        require(objectStart >= 0, "object start: " + objectKey);
        if (nested) {
            int outerKeyStart = source.indexOf('"', objectStart + 1);
            int outerKeyEnd = findStringEnd(source, outerKeyStart);
            int outerColon = source.indexOf(':', outerKeyEnd);
            objectStart = source.indexOf('{', outerColon);
            require(objectStart >= 0, "nested object start: " + objectKey);
        }
        int keyStart = source.indexOf('"', objectStart + 1);
        int keyEnd = findStringEnd(source, keyStart);
        int colon = source.indexOf(':', keyEnd);
        int valueStart = skipWhitespace(source, colon + 1);
        int valueEnd = valueStart;
        while (valueEnd < source.length()
                && "-+0123456789.eE".indexOf(source.charAt(valueEnd)) >= 0) {
            valueEnd++;
        }
        require(valueEnd > valueStart, "numeric object value");
        return source.substring(0, valueStart) + replacement + source.substring(valueEnd);
    }

    private static String replaceFirstFeatureName(String source, String replacement) {
        int marker = source.indexOf("\"feature_counts\"");
        int outerStart = source.indexOf('{', marker);
        int labelStart = source.indexOf('"', outerStart + 1);
        int labelEnd = findStringEnd(source, labelStart);
        int labelColon = source.indexOf(':', labelEnd);
        int countsStart = source.indexOf('{', labelColon);
        int featureStart = source.indexOf('"', countsStart + 1);
        int featureEnd = findStringEnd(source, featureStart);
        require(featureStart >= 0 && featureEnd > featureStart, "feature name");
        return source.substring(0, featureStart + 1)
                + replacement
                + source.substring(featureEnd);
    }

    private static String replaceFirstObjectKey(
            String source,
            String objectKey,
            String replacement
    ) {
        int marker = source.indexOf("\"" + objectKey + "\"");
        require(marker >= 0, "missing object: " + objectKey);
        int objectStart = source.indexOf('{', marker);
        int keyStart = source.indexOf('"', objectStart + 1);
        int keyEnd = findStringEnd(source, keyStart);
        require(keyStart >= 0 && keyEnd > keyStart, "object key");
        return source.substring(0, keyStart + 1)
                + replacement
                + source.substring(keyEnd - 1);
    }

    private static String duplicateFirstArrayString(String source, String arrayKey) {
        int marker = source.indexOf("\"" + arrayKey + "\"");
        require(marker >= 0, "missing array: " + arrayKey);
        int arrayStart = source.indexOf('[', marker);
        int stringStart = source.indexOf('"', arrayStart + 1);
        int stringEnd = findStringEnd(source, stringStart);
        require(stringStart >= 0 && stringEnd > stringStart, "array string");
        String encodedValue = source.substring(stringStart, stringEnd);
        return source.substring(0, stringStart)
                + encodedValue
                + ","
                + source.substring(stringStart);
    }

    private static int findJsonValueEnd(String source, int start) {
        char first = source.charAt(start);
        if (first == '"') {
            return findStringEnd(source, start);
        }
        if (first == '{' || first == '[') {
            char open = first;
            char close = first == '{' ? '}' : ']';
            int depth = 0;
            boolean inString = false;
            boolean escaped = false;
            for (int index = start; index < source.length(); index++) {
                char current = source.charAt(index);
                if (inString) {
                    if (escaped) {
                        escaped = false;
                    } else if (current == '\\') {
                        escaped = true;
                    } else if (current == '"') {
                        inString = false;
                    }
                } else if (current == '"') {
                    inString = true;
                } else if (current == open) {
                    depth++;
                } else if (current == close && --depth == 0) {
                    return index + 1;
                }
            }
            throw new AssertionError("unterminated JSON container");
        }
        int end = start;
        while (end < source.length()
                && source.charAt(end) != ','
                && source.charAt(end) != '}'
                && source.charAt(end) != ']'
                && !Character.isWhitespace(source.charAt(end))) {
            end++;
        }
        return end;
    }

    private static int findStringEnd(String source, int start) {
        require(start >= 0 && source.charAt(start) == '"', "string start");
        boolean escaped = false;
        for (int index = start + 1; index < source.length(); index++) {
            char current = source.charAt(index);
            if (escaped) {
                escaped = false;
            } else if (current == '\\') {
                escaped = true;
            } else if (current == '"') {
                return index + 1;
            }
        }
        throw new AssertionError("unterminated JSON string");
    }

    private static int skipWhitespace(String source, int start) {
        int index = start;
        while (index < source.length() && Character.isWhitespace(source.charAt(index))) {
            index++;
        }
        return index;
    }

    private static void expectUnsupported(ThrowingRunnable action) {
        try {
            action.run();
            throw new AssertionError("expected immutable collection");
        } catch (UnsupportedOperationException expected) {
            // Expected.
        } catch (Exception error) {
            throw new AssertionError("unexpected exception", error);
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    @FunctionalInterface
    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
