import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class MiniJson {
    private MiniJson() {}

    public static Object parse(String source) {
        if (source == null) {
            throw new IllegalArgumentException("JSON error at position 0: source must not be null");
        }
        return new Parser(source).parseDocument();
    }

    private static final class Parser {
        private final String source;
        private int position;

        private Parser(String source) {
            this.source = source;
        }

        private Object parseDocument() {
            skipWhitespace();
            Object value = parseValue();
            skipWhitespace();
            if (position != source.length()) {
                throw error("unexpected trailing character " + describe(source.charAt(position)));
            }
            return value;
        }

        private Object parseValue() {
            if (position >= source.length()) {
                throw error("expected a JSON value");
            }
            return switch (source.charAt(position)) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> parseString();
                case 't' -> parseLiteral("true", Boolean.TRUE);
                case 'f' -> parseLiteral("false", Boolean.FALSE);
                case 'n' -> parseLiteral("null", null);
                case '-' -> parseNumber();
                default -> {
                    char current = source.charAt(position);
                    if (current >= '0' && current <= '9') {
                        yield parseNumber();
                    }
                    throw error("unexpected character " + describe(current));
                }
            };
        }

        private Map<String, Object> parseObject() {
            position++;
            skipWhitespace();
            Map<String, Object> result = new LinkedHashMap<>();
            if (consume('}')) {
                return result;
            }
            while (true) {
                if (position >= source.length() || source.charAt(position) != '"') {
                    throw error("expected a quoted object key");
                }
                int keyPosition = position;
                String key = parseString();
                skipWhitespace();
                require(':', "expected ':' after object key");
                skipWhitespace();
                Object value = parseValue();
                if (result.containsKey(key)) {
                    throw errorAt(keyPosition, "duplicate object key " + quote(key));
                }
                result.put(key, value);
                skipWhitespace();
                if (consume('}')) {
                    return result;
                }
                require(',', "expected ',' or '}' in object");
                skipWhitespace();
            }
        }

        private List<Object> parseArray() {
            position++;
            skipWhitespace();
            List<Object> result = new ArrayList<>();
            if (consume(']')) {
                return result;
            }
            while (true) {
                result.add(parseValue());
                skipWhitespace();
                if (consume(']')) {
                    return result;
                }
                require(',', "expected ',' or ']' in array");
                skipWhitespace();
            }
        }

        private String parseString() {
            int stringPosition = position;
            position++;
            StringBuilder result = new StringBuilder();
            while (position < source.length()) {
                char current = source.charAt(position++);
                if (current == '"') {
                    validateSurrogates(result, stringPosition);
                    return result.toString();
                }
                if (current < 0x20) {
                    throw errorAt(position - 1, "unescaped control character in string");
                }
                if (current != '\\') {
                    result.append(current);
                    continue;
                }
                if (position >= source.length()) {
                    throw error("unterminated string escape");
                }
                char escape = source.charAt(position++);
                switch (escape) {
                    case '"' -> result.append('"');
                    case '\\' -> result.append('\\');
                    case '/' -> result.append('/');
                    case 'b' -> result.append('\b');
                    case 'f' -> result.append('\f');
                    case 'n' -> result.append('\n');
                    case 'r' -> result.append('\r');
                    case 't' -> result.append('\t');
                    case 'u' -> result.append(parseUnicodeEscape());
                    default -> throw errorAt(
                            position - 1,
                            "invalid string escape '\\" + escape + "'"
                    );
                }
            }
            throw errorAt(stringPosition, "unterminated string");
        }

        private char parseUnicodeEscape() {
            int escapeDigits = position;
            if (source.length() - position < 4) {
                throw error("Unicode escape must contain four hexadecimal digits");
            }
            int value = 0;
            for (int offset = 0; offset < 4; offset++) {
                char digit = source.charAt(position++);
                int hexadecimal = hexadecimalValue(digit);
                if (hexadecimal < 0) {
                    throw errorAt(
                            escapeDigits + offset,
                            "Unicode escape contains a non-hexadecimal digit"
                    );
                }
                value = value * 16 + hexadecimal;
            }
            return (char) value;
        }

        private void validateSurrogates(CharSequence value, int stringPosition) {
            for (int index = 0; index < value.length(); index++) {
                char current = value.charAt(index);
                if (Character.isHighSurrogate(current)) {
                    if (index + 1 >= value.length()
                            || !Character.isLowSurrogate(value.charAt(index + 1))) {
                        throw errorAt(
                                stringPosition,
                                "string contains an isolated high surrogate"
                        );
                    }
                    index++;
                } else if (Character.isLowSurrogate(current)) {
                    throw errorAt(
                            stringPosition,
                            "string contains an isolated low surrogate"
                    );
                }
            }
        }

        private Object parseNumber() {
            int start = position;
            consume('-');
            if (position >= source.length()) {
                throw error("number requires an integer part");
            }
            if (consume('0')) {
                if (position < source.length() && isDigit(source.charAt(position))) {
                    throw error("leading zero is not allowed in a JSON number");
                }
            } else {
                if (!isDigitOneToNine(source.charAt(position))) {
                    throw error("number requires an integer part");
                }
                while (position < source.length() && isDigit(source.charAt(position))) {
                    position++;
                }
            }

            boolean integer = true;
            if (consume('.')) {
                integer = false;
                int fractionStart = position;
                while (position < source.length() && isDigit(source.charAt(position))) {
                    position++;
                }
                if (position == fractionStart) {
                    throw error("fraction requires at least one digit");
                }
            }
            if (position < source.length()
                    && (source.charAt(position) == 'e' || source.charAt(position) == 'E')) {
                integer = false;
                position++;
                if (position < source.length()
                        && (source.charAt(position) == '+' || source.charAt(position) == '-')) {
                    position++;
                }
                int exponentStart = position;
                while (position < source.length() && isDigit(source.charAt(position))) {
                    position++;
                }
                if (position == exponentStart) {
                    throw error("exponent requires at least one digit");
                }
            }

            String token = source.substring(start, position);
            if (integer) {
                try {
                    return Long.parseLong(token);
                } catch (NumberFormatException ignored) {
                    return new BigDecimal(token);
                }
            }
            double value;
            try {
                value = Double.parseDouble(token);
            } catch (NumberFormatException error) {
                throw errorAt(start, "invalid JSON number");
            }
            if (!Double.isFinite(value)) {
                throw errorAt(start, "JSON number does not have a finite double value");
            }
            return value;
        }

        private Object parseLiteral(String literal, Object value) {
            if (!source.startsWith(literal, position)) {
                throw error("invalid literal; expected " + literal);
            }
            position += literal.length();
            return value;
        }

        private void skipWhitespace() {
            while (position < source.length()) {
                char current = source.charAt(position);
                if (current != ' ' && current != '\t' && current != '\r' && current != '\n') {
                    return;
                }
                position++;
            }
        }

        private boolean consume(char expected) {
            if (position < source.length() && source.charAt(position) == expected) {
                position++;
                return true;
            }
            return false;
        }

        private void require(char expected, String message) {
            if (!consume(expected)) {
                throw error(message);
            }
        }

        private IllegalArgumentException error(String message) {
            return errorAt(position, message);
        }

        private IllegalArgumentException errorAt(int errorPosition, String message) {
            return new IllegalArgumentException(
                    "JSON error at position " + errorPosition + ": " + message
            );
        }

        private static boolean isDigit(char value) {
            return value >= '0' && value <= '9';
        }

        private static boolean isDigitOneToNine(char value) {
            return value >= '1' && value <= '9';
        }

        private static int hexadecimalValue(char value) {
            if (value >= '0' && value <= '9') {
                return value - '0';
            }
            if (value >= 'a' && value <= 'f') {
                return value - 'a' + 10;
            }
            if (value >= 'A' && value <= 'F') {
                return value - 'A' + 10;
            }
            return -1;
        }

        private static String describe(char value) {
            return "'" + value + "'";
        }

        private static String quote(String value) {
            return "'" + value + "'";
        }
    }
}
