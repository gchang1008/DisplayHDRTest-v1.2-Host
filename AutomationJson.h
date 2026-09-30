#pragma once

#include <winrt/Windows.Data.Json.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <cmath>
#include <stdexcept>

namespace Automation
{
    using namespace winrt::Windows::Data::Json;

    struct Error : std::runtime_error
    {
        std::wstring code;
        Error(const wchar_t* value, const char* message) : std::runtime_error(message), code(value) {}
    };

    inline void Put(JsonObject const& object, wchar_t const* key, bool value)
    { object.SetNamedValue(key, JsonValue::CreateBooleanValue(value)); }
    inline void Put(JsonObject const& object, wchar_t const* key, double value)
    { object.SetNamedValue(key, std::isfinite(value) ? JsonValue::CreateNumberValue(value) : JsonValue::CreateNullValue()); }
    inline void Put(JsonObject const& object, wchar_t const* key, std::wstring const& value)
    { object.SetNamedValue(key, JsonValue::CreateStringValue(value)); }
    inline void Put(JsonObject const& object, wchar_t const* key, wchar_t const* value)
    { Put(object, key, std::wstring(value)); }

    inline void Require(bool condition, const char* message)
    { if (!condition) throw Error(L"invalid_request", message); }

    inline double Number(IJsonValue const& value, double minimum, double maximum, bool integral = false)
    {
        Require(value.ValueType() == JsonValueType::Number, "Expected a number.");
        double number = value.GetNumber();
        Require(std::isfinite(number) && number >= minimum && number <= maximum,
            "Number is outside the supported range.");
        Require(!integral || std::floor(number) == number, "Expected an integer.");
        return number;
    }

    inline bool Boolean(IJsonValue const& value)
    {
        Require(value.ValueType() == JsonValueType::Boolean, "Expected a boolean.");
        return value.GetBoolean();
    }

    inline std::wstring String(IJsonValue const& value)
    {
        Require(value.ValueType() == JsonValueType::String, "Expected a string.");
        return std::wstring(value.GetString());
    }

    inline JsonObject Failure(std::wstring const& id, wchar_t const* code, std::wstring const& message)
    {
        JsonObject response, error;
        Put(response, L"version", 1.0);
        Put(response, L"id", id);
        Put(response, L"ok", false);
        Put(error, L"code", code);
        Put(error, L"message", message);
        response.SetNamedValue(L"error", error);
        return response;
    }
}
