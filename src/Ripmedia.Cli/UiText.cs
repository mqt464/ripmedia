internal static class UiText
{
    public static string Truncate(string text, int maximumLength = 72) =>
        text.Length <= maximumLength ? text : text[..(maximumLength - 3)] + "...";
}
