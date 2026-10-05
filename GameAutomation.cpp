#include "pch.h"
#include "Game.h"
#include "AutomationJson.h"
#include <cfloat>

// Use the original conversion functions defined by Game.cpp/ColorSpaces.h.
float Apply2084(float);
float Remove2084(float);
float ApplySRGBCurve(float);
float RemoveSRGBCurve(float);

using namespace Automation;

namespace
{
    struct TestInfo { Game::TestPattern pattern; wchar_t const* id; wchar_t const* title; };
    TestInfo const tests[] = {
        { Game::TestPattern::StartOfTest, L"StartOfTest", L"Home.   Start Screen" },
        { Game::TestPattern::ConnectionProperties, L"ConnectionProperties", L"Connection properties:" },
        { Game::TestPattern::PanelCharacteristics, L"PanelCharacteristics", L"Reported Panel Characteristics" },
        { Game::TestPattern::ResetInstructions, L"ResetInstructions", L"Start of performance tests" },
        { Game::TestPattern::PQLevelsInNits, L"PQLevelsInNits", L"PQ/ST 2084 levels in nits" },
        { Game::TestPattern::WarmUp, L"WarmUp", L"Warm-Up:" },
        { Game::TestPattern::TenPercentPeak, L"TenPercentPeak", L"1.a Peak Luminance @ 8.00% screen area" },
        { Game::TestPattern::TenPercentPeakMAX, L"TenPercentPeakMAX", L"1.b Peak Luminance MAX @ 8.00% screen area" },
        { Game::TestPattern::FlashTest, L"FlashTest", L"2.a Flash Test Off" },
        { Game::TestPattern::FlashTestMAX, L"FlashTestMAX", L"2.b MAX Flash Test Off" },
        { Game::TestPattern::LongDurationWhite, L"LongDurationWhite", L"3.a Full-frame white for 30 minutes:" },
        { Game::TestPattern::FullFramePeak, L"FullFramePeak", L"3.b Full-frame white for 30 minutes:" },
        { Game::TestPattern::DualCornerBox, L"DualCornerBox", L"4. Corner test for Total Contrast" },
        { Game::TestPattern::StaticContrastRatio, L"StaticContrastRatio", L"5. Static Contrast Ratio" },
        { Game::TestPattern::ActiveDimming, L"ActiveDimming", L"5.1 Active Dimming" },
        { Game::TestPattern::ActiveDimmingDark, L"ActiveDimmingDark", L"5.2 Active Dimming Dark" },
        { Game::TestPattern::ActiveDimmingSplit, L"ActiveDimmingSplit", L"5.3 Active Dimming Splitscreen" },
        { Game::TestPattern::ColorPatches, L"ColorPatches", L"6. Checking Red Chromaticity Point" },
        { Game::TestPattern::ColorPatchesFull, L"ColorPatchesFull", L"6. Checking Red Chromaticity Point" },
        { Game::TestPattern::BitDepthPrecision, L"BitDepthPrecision", L"7. Bit-Depth/Precision" },
        { Game::TestPattern::RiseFallTime, L"RiseFallTime", L"8. Rise/Fall Time" },
        { Game::TestPattern::ProfileCurve, L"ProfileCurve", L"9. Validating 2084 Profile Curve in nits" },
        { Game::TestPattern::LocalDimmingContrast, L"LocalDimmingContrast", L"1.2.1 Contrast test for Local Dimming:" },
        { Game::TestPattern::BlackLevelHDRvsSDR, L"BlackLevelHDRvsSDR", L"1.2.2 Black Level in HDR vs SDR" },
        { Game::TestPattern::BlackLevelCrush, L"BlackLevelCrush", L"v1.2.3 Black Level Crush Test:" },
        { Game::TestPattern::SubTitleFlicker, L"SubTitleFlicker", L"1.2.4 Subtitle Flicker Test:" },
        { Game::TestPattern::XRiteColors, L"XRiteColors", L"1.2.5 X-Rite\u2122 Colors" },
        { Game::TestPattern::EndOfMandatoryTests, L"EndOfMandatoryTests", L"This is the end of mandatory test content." },
        { Game::TestPattern::SharpeningFilter, L"SharpeningFilter", L"Fresnel zone plate (sharpening test)" },
        { Game::TestPattern::ToneMapSpike, L"ToneMapSpike", L"ST.2084 Spike (Tone map test)" },
        { Game::TestPattern::TextQuality, L"TextQuality", L"Antialiased text (ClearType and grayscale)" },
        { Game::TestPattern::OnePixelLinesBW, L"OnePixelLinesBW", L"Single pixel lines (black/white)" },
        { Game::TestPattern::OnePixelLinesRG, L"OnePixelLinesRG", L"Single pixel lines (red/green)" },
        { Game::TestPattern::ColorPatches709, L"ColorPatches709", L"709 primaries" },
        { Game::TestPattern::FullFrameSDRWhite, L"FullFrameSDRWhite", L"Full frame SDR white" },
        { Game::TestPattern::FullFrameSDRWhiteWithHDR, L"FullFrameSDRWhiteWithHDR", L"Full frame SDR white with 10% HDR window" },
        { Game::TestPattern::CalibrateMaxEffectiveValue, L"CalibrateMaxEffectiveValue", L"Calibrate Max Tone Mapped Luminance Value:" },
        { Game::TestPattern::CalibrateMaxEffectiveFullFrameValue, L"CalibrateMaxEffectiveFullFrameValue", L"Calibrate Max Full Frame Luminance Value:" },
        { Game::TestPattern::CalibrateMinEffectiveValue, L"CalibrateMinEffectiveValue", L"Calibrate Min Tone-Mapped Luminance Level:" },
        { Game::TestPattern::StaticGradient, L"StaticGradient", L"Static Gradient:" },
        { Game::TestPattern::AnimatedGrayGradient, L"AnimatedGrayGradient", L"Animated Gray Gradient" },
        { Game::TestPattern::AnimatedColorGradient, L"AnimatedColorGradient", L"Animated Color Gradient" },
        { Game::TestPattern::BlackLevelHdrCorners, L"BlackLevelHdrCorners", L"4. Corner test for HDR black level" },
        { Game::TestPattern::BlackLevelSdrTunnel, L"BlackLevelSdrTunnel", L"5. Tunnel for SDR black level" },
        { Game::TestPattern::ColorPatchesMAX, L"ColorPatchesMAX", L"6.b Checking Red Chromaticity Point" },
        { Game::TestPattern::EndOfTest, L"EndOfTest", L"This is the end of the test content." },
        { Game::TestPattern::Cooldown, L"Cooldown", L"Cool-down:" }
    };
    wchar_t const* colors[] = { L"Red", L"Green", L"Blue", L"White" };
    wchar_t const* checkerboards[] = { L"6x4", L"4x3", L"4x3-inverted" };
    int const tiers[] = { 400, 500, 600, 1000, 1400, 2000, 3000, 4000, 6000, 10000 };
    float const blackNits[] = { 0.5f, 0.3f, 0.1f, 0.05f, 0.0f };
    unsigned const profileCodes[] = {
        1023, 0, 8, 16, 24, 36, 48, 56, 64, 120, 156, 256, 340, 384, 452,
        488, 520, 592, 616, 636, 660, 664, 668, 688, 692, 704, 708, 712, 728,
        744, 756, 760, 764, 768, 788, 804, 808, 812, 828, 840, 844, 872, 892, 920, 1023
    };

    template<size_t N> int Find(std::wstring const& value, wchar_t const* const (&values)[N])
    {
        for (size_t i = 0; i < N; ++i) if (value == values[i]) return static_cast<int>(i);
        throw Error(L"invalid_request", "Unsupported enumeration value.");
    }

    TestInfo const& Info(Game::TestPattern pattern)
    {
        for (auto const& test : tests) if (test.pattern == pattern) return test;
        throw Error(L"unsupported_test", "Unknown test pattern.");
    }


}

// Kept in member functions so only the API bridge can access Game's private state.
winrt::Windows::Data::Json::JsonObject Game::AutomationSettings()
{
    JsonObject settings, gradient;
    Put(settings, L"textVisible", m_showExplanatoryText);
    Put(settings, L"subtitlesVisible", (m_subtitleVisible & 1) != 0);
    Put(settings, L"paused", m_bPaused);
    Put(settings, L"fullscreen", m_automationFullscreen());
    Put(settings, L"color", colors[m_currentColor]);
    Put(settings, L"testingTier", static_cast<double>(tiers[m_testingTier]));
    Put(settings, L"checkerboard", checkerboards[static_cast<int>(m_checkerboard)]);
    Put(settings, L"whiteLevel", static_cast<double>(WhiteLevelBrackets[m_whiteLevelBracket]));
    Put(settings, L"blackIndex", static_cast<double>(m_currentBlack));
    Put(settings, L"profileIndex", static_cast<double>(m_currentProfileTile));
    Put(settings, L"xriteIndex", static_cast<double>(m_currentXRiteIndex));
    Put(settings, L"xriteAuto", m_XRitePatchAutoMode);
    Put(settings, L"xriteInterval", static_cast<double>(m_XRitePatchDisplayTime));
    Put(settings, L"dimmingMode", m_LocalDimmingBars == 0 ? L"1D" : L"2D");
    Put(gradient, L"r", static_cast<double>(m_gradientColor.r));
    Put(gradient, L"g", static_cast<double>(m_gradientColor.g));
    Put(gradient, L"b", static_cast<double>(m_gradientColor.b));
    settings.SetNamedValue(L"gradient", gradient);
    auto const& floats = AutomationFloats();
    for (auto const& value : floats) Put(settings, value.key, static_cast<double>(this->*value.member));
    return settings;
}

void Game::ConfigureAutomation(HWND window, std::function<void(bool)> setFullscreen,
    std::function<bool()> getFullscreen)
{
    m_automationWindow = window;
    m_automationSetFullscreen = std::move(setFullscreen);
    m_automationFullscreen = std::move(getFullscreen);
    m_automationDefaults = AutomationSettings();
}

void Game::QueueAutomationState(JsonObject const& request, std::wstring const& id)
{
    Require(!m_automationPending, "A state change is already pending.");
    TestPattern target = m_currentTest;
    if (request.HasKey(L"test"))
    {
        auto name = String(request.GetNamedValue(L"test"));
        bool found = false;
        for (auto const& test : tests) if (name == test.id) { target = test.pattern; found = true; break; }
        if (!found) throw Error(L"unsupported_test", "Unknown test id. Use catalog to list test ids.");
    }
    if (request.HasKey(L"restart")) Boolean(request.GetNamedValue(L"restart"));
    JsonObject values = request.HasKey(L"settings") ? request.GetNamedObject(L"settings") : JsonObject();
    auto const& floats = AutomationFloats();
    if (values.HasKey(L"nits"))
    {
        float nits = static_cast<float>(Number(values.GetNamedValue(L"nits"), 0, 10000));
        wchar_t const* key = nullptr;
        bool pq = true;
        switch (target)
        {
        case TestPattern::ActiveDimming: key = L"activeDimmingPq"; break;
        case TestPattern::ActiveDimmingDark: key = L"activeDimmingDarkPq"; break;
        case TestPattern::StaticContrastRatio:
            pq = CheckHDR_On(); key = pq ? L"staticContrastPq" : L"staticContrastSrgb"; break;
        case TestPattern::CalibrateMaxEffectiveValue:
            pq = CheckHDR_On(); key = pq ? L"calibrationMaxPq" : L"calibrationMaxSrgb"; break;
        case TestPattern::CalibrateMaxEffectiveFullFrameValue:
            pq = CheckHDR_On(); key = pq ? L"calibrationFullFramePq" : L"calibrationFullFrameSrgb"; break;
        case TestPattern::CalibrateMinEffectiveValue:
            pq = CheckHDR_On(); key = pq ? L"calibrationMinPq" : L"calibrationMinSrgb"; break;
        default: throw Error(L"unsupported_setting", "Nits is derived/read-only for this test. Set its index or level instead.");
        }
        Require(!values.HasKey(key), "Do not specify both nits and its raw code value.");
        double code = pq ? Apply2084(nits / 10000.0f) * 1023.0f : ApplySRGBCurve(nits / 80.0f) * 255.0f;
        for (auto const& field : floats) if (std::wstring(key) == field.key)
            Require(code >= field.low && code <= field.high, "Nits is outside this test's supported range.");
        Put(values, key, code);
        values.Remove(L"nits");
    }
    for (auto const& entry : values)
    {
        auto key = std::wstring(entry.Key());
        auto value = entry.Value();
        if (key == L"textVisible" || key == L"subtitlesVisible" || key == L"paused"
            || key == L"fullscreen" || key == L"xriteAuto") Boolean(value);
        else if (key == L"color") Find(String(value), colors);
        else if (key == L"checkerboard") Find(String(value), checkerboards);
        else if (key == L"dimmingMode") Require(String(value) == L"1D" || String(value) == L"2D", "Expected 1D or 2D.");
        else if (key == L"testingTier")
        {
            double number = Number(value, 400, 10000, true);
            Require(std::find(std::begin(tiers), std::end(tiers), number) != std::end(tiers), "Unknown testing tier.");
        }
        else if (key == L"whiteLevel")
        {
            double number = Number(value, 50, 1000, true);
            Require(std::find(std::begin(WhiteLevelBrackets), std::end(WhiteLevelBrackets), number)
                != std::end(WhiteLevelBrackets), "Unknown white level bracket.");
        }
        else if (key == L"blackIndex") Number(value, 0, 4, true);
        else if (key == L"profileIndex") Number(value, 0, AutomationProfileMaximum(), true);
        else if (key == L"xriteIndex") Number(value, 0, 97, true);
        else if (key == L"xriteInterval") Number(value, 0.001, FLT_MAX);
        else if (key == L"gradient")
        {
            Require(value.ValueType() == JsonValueType::Object, "Expected an RGB object.");
            auto rgb = value.GetObject();
            Require(rgb.Size() == 3 && rgb.HasKey(L"r") && rgb.HasKey(L"g") && rgb.HasKey(L"b"), "Expected r, g and b.");
            for (auto const& channel : rgb) Number(channel.Value(), -FLT_MAX, FLT_MAX);
        }
        else
        {
            bool found = false;
            for (auto const& field : floats) if (key == field.key)
            { Number(value, field.low, field.high); found = true; break; }
            if (!found) throw Error(L"unsupported_setting", "Unknown or read-only setting.");
        }
    }
    // Nothing is changed until the entire request passes validation.
    m_automationTarget = target;
    m_automationRestart = request.HasKey(L"restart") && request.GetNamedBoolean(L"restart");
    m_automationRequestId = id;
    m_automationPending = values;
}

void Game::QueueAutomationKey(JsonObject const& request, std::wstring const& id)
{
    Require(!m_automationPending, "A state change is already pending.");
    Require(request.HasKey(L"key"), "Missing key.");
    auto key = String(request.GetNamedValue(L"key"));
    bool shift = key.compare(0, 6, L"Shift+") == 0;
    if (shift) key = key.substr(6);
    bool digit = key.size() == 1 && key[0] >= L'0' && key[0] <= L'9';
    wchar_t const* allowed[] = { L"Up", L"Down", L"Left", L"Right", L"PageUp", L"PageDown",
        L"Space", L"Home", L"Control", L"C", L"P", L"Pause", L"A", L"Period", L"Comma",
        L"Plus", L"Minus", L"LeftBracket", L"RightBracket", L"Escape", L"AltEnter" };
    if (!digit) Find(key, allowed);
    m_automationKey = String(request.GetNamedValue(L"key"));
    m_automationTarget = m_currentTest;
    m_automationRestart = false;
    m_automationRequestId = id;
    m_automationPending = JsonObject();
}

void Game::ApplyAutomationKey()
{
    auto key = m_automationKey;
    bool shift = key.compare(0, 6, L"Shift+") == 0;
    if (shift) key = key.substr(6);
    bool localShift = GetShift();
    SetShift(shift);
    bool digit = key.size() == 1 && key[0] >= L'0' && key[0] <= L'9';
    if (digit)
    {
        TestPattern const normal[] = { TestPattern::ConnectionProperties, TestPattern::TenPercentPeak,
            TestPattern::FlashTest, TestPattern::LongDurationWhite, TestPattern::DualCornerBox,
            TestPattern::StaticContrastRatio, TestPattern::ColorPatches, TestPattern::BitDepthPrecision,
            TestPattern::RiseFallTime, TestPattern::ProfileCurve };
        TestPattern const shifted[] = { TestPattern::ConnectionProperties, TestPattern::LocalDimmingContrast,
            TestPattern::BlackLevelHDRvsSDR, TestPattern::BlackLevelCrush, TestPattern::SubTitleFlicker,
            TestPattern::XRiteColors };
        size_t index = key[0] - L'0';
        if (!shift) SetTestPattern(normal[index]);
        else if (index < std::size(shifted)) SetTestPattern(shifted[index]);
    }
    else if (key == L"Up" || key == L"Down")
    {
        ChangeSubtest(key == L"Up" ? 1 : -1);
    }
    else if (key == L"Right" || key == L"PageDown") ChangeTestPattern(true);
    else if (key == L"Left" || key == L"PageUp") ChangeTestPattern(false);
    else if (key == L"Space") ToggleInfoTextVisible();
    else if (key == L"Home") StartTestPattern();
    else if (key == L"Control") ToggleSubtitle();
    else if (key == L"C") SetTestPattern(TestPattern::Cooldown);
    else if (key == L"P" || key == L"Pause") PauseAnimation();
    else if (key == L"A") ToggleXRitePatchAuto();
    else if (key == L"Period" || key == L"Comma") ChangeCheckerboard(key == L"Period" ? 1 : -1);
    else if (key == L"Plus" || key == L"Minus") ChangeXRitePatchDisplayTime(key == L"Plus" ? 1 : -1);
    else if (key == L"LeftBracket" || key == L"RightBracket") SelectWhiteLevel(key == L"RightBracket" ? 1 : -1);
    else if (key == L"Escape") m_automationSetFullscreen(false);
    else if (key == L"AltEnter") m_automationSetFullscreen(!m_automationFullscreen());
    SetShift(localShift);
    m_automationTarget = m_currentTest;
    m_automationKey.clear();
}

void Game::BeginAutomationUpdate()
{
    if (!m_automationPending || m_automationBegun) return;
    if (!m_automationKey.empty()) ApplyAutomationKey();
    if (m_automationPending.HasKey(L"fullscreen"))
        m_automationSetFullscreen(m_automationPending.GetNamedBoolean(L"fullscreen"));
    if (m_currentTest != m_automationTarget || m_automationRestart) SetTestPattern(m_automationTarget);
    // Update builds the gradient brush, so its input must be applied first.
    if (m_automationPending.HasKey(L"gradient"))
    {
        auto rgb = m_automationPending.GetNamedObject(L"gradient");
        m_gradientColor.r = static_cast<float>(rgb.GetNamedNumber(L"r"));
        m_gradientColor.g = static_cast<float>(rgb.GetNamedNumber(L"g"));
        m_gradientColor.b = static_cast<float>(rgb.GetNamedNumber(L"b"));
    }
    m_automationBegun = true;
}

void Game::ApplyAutomationSettings()
{
    if (!m_automationBegun) return;
    auto values = m_automationPending;
    auto setBool = [&](wchar_t const* key, bool& field) { if (values.HasKey(key)) field = values.GetNamedBoolean(key); };
    auto setInt = [&](wchar_t const* key, INT32& field) { if (values.HasKey(key)) field = static_cast<INT32>(values.GetNamedNumber(key)); };
    auto setFloat = [&](wchar_t const* key, float& field) { if (values.HasKey(key)) field = static_cast<float>(values.GetNamedNumber(key)); };
    setBool(L"textVisible", m_showExplanatoryText);
    setBool(L"paused", m_bPaused);
    if (values.HasKey(L"subtitlesVisible")) m_subtitleVisible = values.GetNamedBoolean(L"subtitlesVisible") ? 1 : 0;
    if (values.HasKey(L"color")) m_currentColor = Find(std::wstring(values.GetNamedString(L"color")), colors);
    if (values.HasKey(L"checkerboard")) m_checkerboard = static_cast<Checkerboard>(Find(std::wstring(values.GetNamedString(L"checkerboard")), checkerboards));
    if (values.HasKey(L"testingTier"))
        m_testingTier = static_cast<TestingTier>(std::find(std::begin(tiers), std::end(tiers), values.GetNamedNumber(L"testingTier")) - std::begin(tiers));
    if (values.HasKey(L"whiteLevel"))
        m_whiteLevelBracket = static_cast<INT32>(std::find(std::begin(WhiteLevelBrackets), std::end(WhiteLevelBrackets), values.GetNamedNumber(L"whiteLevel")) - std::begin(WhiteLevelBrackets));
    setInt(L"blackIndex", m_currentBlack);
    setInt(L"profileIndex", m_currentProfileTile);
    setInt(L"xriteIndex", m_currentXRiteIndex);
    bool intervalChanged = values.HasKey(L"xriteInterval")
        && m_XRitePatchDisplayTime != static_cast<float>(values.GetNamedNumber(L"xriteInterval"));
    setFloat(L"xriteInterval", m_XRitePatchDisplayTime);
    if (values.HasKey(L"xriteAuto"))
    {
        bool enabled = values.GetNamedBoolean(L"xriteAuto");
        if (enabled && !m_XRitePatchAutoMode)
        {
            if (!values.HasKey(L"xriteIndex")) m_currentXRiteIndex = 0;
            m_automationResetXriteTimer = true;
        }
        m_XRitePatchAutoMode = enabled;
    }
    if (intervalChanged && m_currentTest == TestPattern::XRiteColors)
        m_automationResetXriteTimer = true;
    for (auto const& field : AutomationFloats()) setFloat(field.key, this->*field.member);
    // Local dimming metadata depends on this subtest, just as with the arrow keys.
    if (values.HasKey(L"dimmingMode"))
    {
        int mode = values.GetNamedString(L"dimmingMode") == L"1D" ? 0 : 1;
        if (mode != m_LocalDimmingBars && m_currentTest == TestPattern::LocalDimmingContrast)
            m_newTestSelected = true;
        m_LocalDimmingBars = mode;
    }
    m_automationLastRequestId = m_automationRequestId;
    m_automationPending = nullptr;
    m_automationBegun = false;
}

JsonObject Game::AutomationState()
{
    JsonObject state, test, effective, presentation, timing, display;
    auto const& info = Info(m_currentTest);
    Put(test, L"id", info.id);
    std::wstring title = info.title;
    if (m_currentTest == TestPattern::ColorPatches || m_currentTest == TestPattern::ColorPatchesFull || m_currentTest == TestPattern::ColorPatchesMAX)
        title = std::wstring(m_currentTest == TestPattern::ColorPatchesMAX ? L"6.b Checking " : L"6. Checking ")
            + colors[m_currentColor] + (m_currentColor == 3 ? L" Point" : L" Chromaticity Point");
    if (m_currentTest == TestPattern::LocalDimmingContrast) title += m_LocalDimmingBars == 0 ? L"  1-D" : L"  2-D";
    if (m_currentTest == TestPattern::FlashTest) title = m_flashOn ? L"2.a Flash Test On" : L"2.a Flash Test Off";
    if (m_currentTest == TestPattern::FlashTestMAX) title = m_flashOn ? L"2.b MAX Flash Test On" : L"2.b MAX Flash Test Off";
    Put(test, L"title", title);
    Put(test, L"titleSource", L"definition");
    Put(test, L"displayedText", m_automationRenderedText);
    state.SetNamedValue(L"test", test);
    auto settings = AutomationSettings();
    Put(state, L"stateVersion", static_cast<double>(m_automationStateVersion));
    Put(state, L"lastSetRequestId", m_automationLastRequestId);
    state.SetNamedValue(L"settings", settings);
    state.SetNamedValue(L"applicableSettings", AutomationApplicableSettings(m_currentTest));
    double nits = NAN, code = NAN;
    bool hdr = CheckHDR_On();
    switch (m_currentTest)
    {
    case TestPattern::ActiveDimming: code = m_activeDimming50PQValue; nits = Remove2084(static_cast<float>(code / 1023)) * 10000.0f; break;
    case TestPattern::ActiveDimmingDark: code = m_activeDimming05PQValue; nits = Remove2084(static_cast<float>(code / 1023)) * 10000.0f; break;
    case TestPattern::ActiveDimmingSplit: nits = 50; Put(effective, L"rightNits", 5.0); code = Apply2084(50.0f / 10000) * 1023; break;
    case TestPattern::StaticContrastRatio:
        code = hdr ? m_staticContrastPQValue : m_staticContrastsRGBValue;
        nits = hdr ? Remove2084(static_cast<float>(code / 1023)) * 10000.0f : RemoveSRGBCurve(static_cast<float>(code / 255)) * 80.0f; break;
    case TestPattern::BlackLevelCrush: nits = blackNits[m_currentBlack]; code = Apply2084(static_cast<float>(nits / 10000)) * 1023; break;
    case TestPattern::ProfileCurve:
        code = std::min(profileCodes[m_currentProfileTile], m_maxPQCode);
        nits = Remove2084(static_cast<float>(code / 1023)) * 10000.0f; break;
    case TestPattern::TenPercentPeak: case TestPattern::FlashTest:
    case TestPattern::LongDurationWhite: case TestPattern::DualCornerBox:
    case TestPattern::BlackLevelHdrCorners: case TestPattern::RiseFallTime:
        nits = m_outputDesc.MaxLuminance; break;
    case TestPattern::TenPercentPeakMAX: case TestPattern::FlashTestMAX:
    case TestPattern::FullFramePeak:
        nits = 10000; break;
    case TestPattern::SubTitleFlicker: nits = 10; break;
    case TestPattern::BlackLevelHDRvsSDR: nits = 200; break;
    case TestPattern::LocalDimmingContrast: nits = m_outputDesc.MaxLuminance; break;
    case TestPattern::ColorPatches: case TestPattern::ColorPatchesFull:
        Put(effective, L"patchAreaFraction", m_currentTest == TestPattern::ColorPatches ? 0.08 : 1.0);
        Put(effective, L"referenceWhiteNits", static_cast<double>(m_outputDesc.MaxLuminance)); break;
    case TestPattern::ColorPatchesMAX:
        Put(effective, L"referenceWhitePq", 636.0); break;
    case TestPattern::ColorPatches709: case TestPattern::XRiteColors:
        Put(effective, L"referenceWhiteNits", static_cast<double>(WhiteLevelBrackets[m_whiteLevelBracket])); break;
    case TestPattern::SharpeningFilter: nits = 80.0 * (m_currentColor + 1); break;
    case TestPattern::ToneMapSpike:
        { double levels[] = { 350, 700, 1015, 10000 }; nits = levels[m_currentColor]; break; }
    case TestPattern::FullFrameSDRWhite:
        nits = 80.0 * (m_currentColor + 1); break;
    case TestPattern::FullFrameSDRWhiteWithHDR:
        { double levels[] = { m_outputDesc.MaxLuminance, 600, 1000, 1400 };
        nits = levels[m_currentColor]; Put(effective, L"backgroundNits", 240.0); break; }
    case TestPattern::CalibrateMaxEffectiveValue:
        code = hdr ? m_maxEffectivePQValue : m_maxEffectivesRGBValue;
        nits = hdr ? Remove2084(static_cast<float>(code / 1023)) * 10000.0f : RemoveSRGBCurve(static_cast<float>(code / 255)) * 80.0f; break;
    case TestPattern::CalibrateMaxEffectiveFullFrameValue:
        code = hdr ? m_maxFullFramePQValue : m_maxFullFramesRGBValue;
        nits = hdr ? Remove2084(static_cast<float>(code / 1023)) * 10000.0f : RemoveSRGBCurve(static_cast<float>(code / 255)) * 80.0f; break;
    case TestPattern::CalibrateMinEffectiveValue:
        code = hdr ? m_minEffectivePQValue : m_minEffectivesRGBValue;
        nits = hdr ? Remove2084(static_cast<float>(code / 1023)) * 10000.0f : RemoveSRGBCurve(static_cast<float>(code / 255)) * 80.0f; break;
    default: break;
    }
    Put(effective, L"nits", nits);
    Put(effective, L"code", code);
    bool srgbCode = !hdr && (m_currentTest == TestPattern::StaticContrastRatio
        || m_currentTest == TestPattern::CalibrateMaxEffectiveValue
        || m_currentTest == TestPattern::CalibrateMaxEffectiveFullFrameValue
        || m_currentTest == TestPattern::CalibrateMinEffectiveValue);
    Put(effective, L"codeEncoding", srgbCode ? L"sRGB" : L"PQ");
    double slider = m_outputDesc.MaxLuminance != 0 ? m_rawOutDesc.MaxLuminance / m_outputDesc.MaxLuminance : NAN;
    double displayedNits = nits;
    switch (m_currentTest)
    {
    case TestPattern::TenPercentPeak: case TestPattern::FlashTest:
    case TestPattern::LongDurationWhite: case TestPattern::DualCornerBox:
    case TestPattern::BlackLevelHdrCorners: case TestPattern::RiseFallTime:
    case TestPattern::StaticContrastRatio: case TestPattern::LocalDimmingContrast:
    case TestPattern::BlackLevelHDRvsSDR: displayedNits *= slider; break;
    default: break;
    }
    Put(effective, L"displayedNits", displayedNits);
    std::wostringstream formatted;
    formatted.imbue(std::locale::classic());
    if (std::isfinite(displayedNits)) formatted << std::fixed << std::setprecision(m_currentTest == TestPattern::ActiveDimmingDark ? 3 : 2) << displayedNits;
    Put(effective, L"nitsText", formatted.str());
    state.SetNamedValue(L"effective", effective);
    bool timed = m_currentTest == TestPattern::WarmUp || m_currentTest == TestPattern::Cooldown
        || m_currentTest == TestPattern::TenPercentPeak || m_currentTest == TestPattern::TenPercentPeakMAX
        || m_currentTest == TestPattern::LongDurationWhite || m_currentTest == TestPattern::FullFramePeak;
    bool phase = m_currentTest == TestPattern::FlashTest || m_currentTest == TestPattern::FlashTestMAX
        || m_currentTest == TestPattern::RiseFallTime || m_currentTest == TestPattern::XRiteColors;
    Put(timing, L"remainingSeconds", timed || phase ? static_cast<double>(m_testTimeRemainingSec) : NAN);
    Put(timing, L"waitComplete", !timed || m_testTimeRemainingSec <= 0);
    if (m_currentTest == TestPattern::FlashTest || m_currentTest == TestPattern::FlashTestMAX || m_currentTest == TestPattern::RiseFallTime)
        Put(timing, L"flashOn", m_flashOn != 0);
    state.SetNamedValue(L"timing", timing);
    bool resources = true;
    auto resourceTest = m_currentTest;
    if (m_currentTest == TestPattern::TenPercentPeakMAX || m_currentTest == TestPattern::RiseFallTime
        || m_currentTest == TestPattern::ProfileCurve || m_currentTest == TestPattern::SubTitleFlicker
        || m_currentTest == TestPattern::XRiteColors
        || (m_currentTest == TestPattern::LocalDimmingContrast && m_LocalDimmingBars == 1))
        resourceTest = TestPattern::TenPercentPeak;
    auto found = m_testPatternResources.find(resourceTest);
    if (found != m_testPatternResources.end())
    {
        auto const& r = found->second;
        resources = (r.imageFilename.empty() || r.imageIsValid) && (r.effectShaderFilename.empty() || r.effectIsValid);
    }
    Put(presentation, L"frameId", static_cast<double>(m_automationFrame));
    Put(presentation, L"lastPresentResult", static_cast<double>(m_deviceResources->GetLastPresentResult()));
    Put(presentation, L"applied", !m_automationPending);
    Put(presentation, L"presented", m_automationPresented && !m_automationPending && resources
        && !IsIconic(m_automationWindow) && IsWindowVisible(m_automationWindow));
    Put(presentation, L"submitted", m_automationPresented && !m_automationPending && resources);
    Put(presentation, L"resourcesValid", resources);
    Put(presentation, L"minimized", IsIconic(m_automationWindow) != FALSE);
    Put(presentation, L"visible", IsWindowVisible(m_automationWindow) != FALSE);
    Put(presentation, L"foreground", GetForegroundWindow() == m_automationWindow);
    state.SetNamedValue(L"presentation", presentation);
    Put(display, L"hdr", hdr);
    Put(display, L"brightnessSliderFactor", slider);
    display.SetNamedValue(L"refreshRateHz", JsonValue::CreateNullValue());
    MONITORINFOEXW monitor = {};
    monitor.cbSize = sizeof(monitor);
    DEVMODEW mode = {};
    mode.dmSize = sizeof(mode);
    auto handle = MonitorFromWindow(m_automationWindow, MONITOR_DEFAULTTONULL);
    if (handle && GetMonitorInfoW(handle, reinterpret_cast<MONITORINFO*>(&monitor))
        && EnumDisplaySettingsExW(monitor.szDevice, ENUM_CURRENT_SETTINGS, &mode, 0)
        && (mode.dmFields & DM_DISPLAYFREQUENCY) && mode.dmDisplayFrequency > 1)
        Put(display, L"refreshRateHz", static_cast<double>(mode.dmDisplayFrequency));
    Put(display, L"backBufferFormat", static_cast<double>(m_deviceResources->GetBackBufferFormat()));
    Put(display, L"width", static_cast<double>(m_modeWidth));
    Put(display, L"height", static_cast<double>(m_modeHeight));
    auto outputSize = m_deviceResources->GetOutputSize();
    Put(display, L"windowWidth", static_cast<double>(outputSize.right - outputSize.left));
    Put(display, L"windowHeight", static_cast<double>(outputSize.bottom - outputSize.top));
    Put(display, L"maxLuminance", static_cast<double>(m_rawOutDesc.MaxLuminance));
    Put(display, L"maxFullFrameLuminance", static_cast<double>(m_rawOutDesc.MaxFullFrameLuminance));
    Put(display, L"minLuminance", static_cast<double>(m_rawOutDesc.MinLuminance));
    Put(display, L"profileMaximumIndex", static_cast<double>(AutomationProfileMaximum()));
    state.SetNamedValue(L"display", display);
    JsonObject metadata;
    Put(metadata, L"maxCLL", static_cast<double>(m_Metadata.MaxContentLightLevel));
    Put(metadata, L"maxFALL", static_cast<double>(m_Metadata.MaxFrameAverageLightLevel));
    Put(metadata, L"maxMastering", static_cast<double>(m_Metadata.MaxMasteringLuminance));
    Put(metadata, L"minMastering", static_cast<double>(m_Metadata.MinMasteringLuminance));
    state.SetNamedValue(L"metadata", metadata);
    return state;
}

JsonObject Game::AutomationCatalog()
{
    JsonObject catalog;
    JsonArray list;
    for (auto const& info : tests)
    {
        JsonObject test;
        Put(test, L"id", info.id);
        Put(test, L"title", info.title);
        test.SetNamedValue(L"applicableSettings", AutomationApplicableSettings(info.pattern));
        list.Append(test);
    }
    catalog.SetNamedValue(L"tests", list);
    // The current persistent settings also provide each field's type and value.
    catalog.SetNamedValue(L"settings", AutomationSettings());
    catalog.SetNamedValue(L"startupDefaults", m_automationDefaults);
    JsonObject schema;
    auto current = AutomationSettings();
    for (auto const& setting : current)
    {
        JsonObject field;
        wchar_t const* type = L"number";
        switch (setting.Value().ValueType())
        {
        case JsonValueType::Boolean: type = L"boolean"; break;
        case JsonValueType::String: type = L"string"; break;
        case JsonValueType::Object: type = L"object"; break;
        default: break;
        }
        Put(field, L"type", type);
        auto key = std::wstring(setting.Key());
        for (auto const& numeric : AutomationFloats()) if (key == numeric.key)
        { Put(field, L"minimum", numeric.low); Put(field, L"maximum", numeric.high); }
        JsonArray allowed;
        if (key == L"color") for (auto value : colors) allowed.Append(JsonValue::CreateStringValue(value));
        if (key == L"checkerboard") for (auto value : checkerboards) allowed.Append(JsonValue::CreateStringValue(value));
        if (key == L"testingTier") for (auto value : tiers) allowed.Append(JsonValue::CreateNumberValue(value));
        if (key == L"whiteLevel") for (auto value : WhiteLevelBrackets) allowed.Append(JsonValue::CreateNumberValue(value));
        if (key == L"dimmingMode") { allowed.Append(JsonValue::CreateStringValue(L"1D")); allowed.Append(JsonValue::CreateStringValue(L"2D")); }
        if (allowed.Size()) field.SetNamedValue(L"allowedValues", allowed);
        if (key == L"blackIndex" || key == L"profileIndex" || key == L"xriteIndex")
        {
            Put(field, L"integer", true);
            Put(field, L"minimum", 0.0);
            Put(field, L"maximum", key == L"blackIndex" ? 4.0 : key == L"xriteIndex" ? 97.0 : static_cast<double>(AutomationProfileMaximum()));
        }
        if (key == L"xriteInterval") { Put(field, L"minimum", 0.001); Put(field, L"maximum", static_cast<double>(FLT_MAX)); Put(field, L"unit", L"seconds"); }
        if (key == L"testingTier" || key == L"whiteLevel") Put(field, L"unit", L"nits");
        for (auto const& numeric : AutomationFloats()) if (key == numeric.key)
            Put(field, L"unit", key.find(L"Pq") != std::wstring::npos ? L"PQ code" : L"sRGB code");
        if (key == L"gradient") Put(field, L"channels", L"r,g,b: finite float32 values");
        schema.SetNamedValue(setting.Key(), field);
    }
    catalog.SetNamedValue(L"settingSchema", schema);
    Put(catalog, L"profileMaximumIndex", static_cast<double>(AutomationProfileMaximum()));
    return catalog;
}

JsonArray Game::AutomationApplicableSettings(TestPattern pattern) const
{
    JsonArray fields;
    auto add = [&](wchar_t const* key) { fields.Append(JsonValue::CreateStringValue(key)); };
    add(L"textVisible"); add(L"fullscreen");
    bool hdr = m_outputDesc.ColorSpace == DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020;
    switch (pattern)
    {
    case TestPattern::PanelCharacteristics: case TestPattern::TenPercentPeak: case TestPattern::TenPercentPeakMAX:
        add(L"testingTier"); break;
    case TestPattern::StaticContrastRatio:
        add(L"checkerboard"); add(hdr ? L"staticContrastPq" : L"staticContrastSrgb"); break;
    case TestPattern::ActiveDimming: add(L"checkerboard"); add(L"activeDimmingPq"); break;
    case TestPattern::ActiveDimmingDark: add(L"checkerboard"); add(L"activeDimmingDarkPq"); break;
    case TestPattern::ActiveDimmingSplit: add(L"checkerboard"); break;
    case TestPattern::ColorPatches: case TestPattern::ColorPatchesFull: case TestPattern::ColorPatchesMAX:
    case TestPattern::FullFrameSDRWhite: case TestPattern::FullFrameSDRWhiteWithHDR: add(L"color"); break;
    case TestPattern::ColorPatches709: add(L"color"); add(L"whiteLevel"); break;
    case TestPattern::SharpeningFilter: case TestPattern::ToneMapSpike: add(L"color"); break;
    case TestPattern::ProfileCurve: add(L"profileIndex"); add(L"paused"); break;
    case TestPattern::LocalDimmingContrast: add(L"dimmingMode"); add(L"paused"); break;
    case TestPattern::BlackLevelCrush: add(L"blackIndex"); break;
    case TestPattern::SubTitleFlicker: add(L"subtitlesVisible"); add(L"paused"); break;
    case TestPattern::XRiteColors:
        add(L"xriteIndex"); add(L"xriteAuto"); add(L"xriteInterval"); add(L"whiteLevel"); add(L"paused"); break;
    case TestPattern::CalibrateMaxEffectiveValue: add(hdr ? L"calibrationMaxPq" : L"calibrationMaxSrgb"); break;
    case TestPattern::CalibrateMaxEffectiveFullFrameValue: add(hdr ? L"calibrationFullFramePq" : L"calibrationFullFrameSrgb"); break;
    case TestPattern::CalibrateMinEffectiveValue: add(hdr ? L"calibrationMinPq" : L"calibrationMinSrgb"); break;
    case TestPattern::StaticGradient: add(L"gradient"); break;
    default: break;
    }
    if (pattern == TestPattern::TenPercentPeak || pattern == TestPattern::TenPercentPeakMAX) add(L"paused");
    return fields;
}

int Game::AutomationProfileMaximum() const
{
    for (int i = 3; i < static_cast<int>(std::size(profileCodes)); ++i)
        if (profileCodes[i] > m_maxPQCode) return i;
    return static_cast<int>(std::size(profileCodes)) - 1;
}

void Game::TrackAutomationPresentation()
{
    if (m_automationResetXriteTimer)
    {
        m_testTimeRemainingSec = m_XRitePatchDisplayTime;
        m_automationResetXriteTimer = false;
    }
    m_automationPresented = m_deviceResources->GetLastPresentResult() == S_OK;
    if (m_automationPresented) ++m_automationFrame;
    std::array<double, 32> current = {
        static_cast<double>(m_currentTest), static_cast<double>(m_testingTier),
        static_cast<double>(m_currentColor), static_cast<double>(m_currentBlack),
        static_cast<double>(m_currentProfileTile), static_cast<double>(m_currentXRiteIndex),
        static_cast<double>(m_checkerboard), static_cast<double>(m_whiteLevelBracket),
        static_cast<double>(m_LocalDimmingBars), static_cast<double>(m_subtitleVisible),
        m_bPaused ? 1.0 : 0.0, m_showExplanatoryText ? 1.0 : 0.0,
        m_XRitePatchAutoMode ? 1.0 : 0.0, m_XRitePatchDisplayTime,
        m_gradientColor.r, m_gradientColor.g, m_gradientColor.b,
        m_maxEffectivePQValue, m_maxFullFramePQValue, m_minEffectivePQValue,
        m_maxEffectivesRGBValue, m_maxFullFramesRGBValue, m_minEffectivesRGBValue,
        m_staticContrastPQValue, m_staticContrastsRGBValue,
        m_activeDimming50PQValue, m_activeDimming05PQValue,
        m_automationFullscreen() ? 1.0 : 0.0,
        static_cast<double>(m_deviceResources->GetBackBufferFormat()),
        static_cast<double>(m_outputDesc.ColorSpace), m_flashOn,
        static_cast<double>(m_maxPQCode)
    };
    if (!m_automationTracked || current != m_automationFingerprint)
    {
        ++m_automationStateVersion;
        m_automationFingerprint = current;
        m_automationTracked = true;
    }
}

std::array<Game::AutomationFloatSetting, 10> const& Game::AutomationFloats()
{
    static std::array<AutomationFloatSetting, 10> const floats = {{
        { L"staticContrastPq", &Game::m_staticContrastPQValue, 100, 750 },
        { L"staticContrastSrgb", &Game::m_staticContrastsRGBValue, 0, 255 },
        { L"activeDimmingPq", &Game::m_activeDimming50PQValue, 420, 488 },
        { L"activeDimmingDarkPq", &Game::m_activeDimming05PQValue, 208, 292 },
        { L"calibrationMaxPq", &Game::m_maxEffectivePQValue, 0, 1023 },
        { L"calibrationFullFramePq", &Game::m_maxFullFramePQValue, 0, 1023 },
        { L"calibrationMinPq", &Game::m_minEffectivePQValue, 0, 1023 },
        { L"calibrationMaxSrgb", &Game::m_maxEffectivesRGBValue, 0, 255 },
        { L"calibrationFullFrameSrgb", &Game::m_maxFullFramesRGBValue, 0, 255 },
        { L"calibrationMinSrgb", &Game::m_minEffectivesRGBValue, 0, 255 }
    }};
    return floats;
}
