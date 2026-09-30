#include "pch.h"
#include "AutomationPipe.h"
#include "AutomationJson.h"
#include "Game.h"

using namespace Automation;

AutomationPipe::Request::Request(std::string value) : input(std::move(value)),
    completed(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {}
AutomationPipe::Request::~Request() { if (completed) CloseHandle(completed); }

AutomationPipe::AutomationPipe() : m_stop(CreateEventW(nullptr, TRUE, FALSE, nullptr))
{
    try { if (m_stop) m_thread = std::thread(&AutomationPipe::Run, this); }
    catch (std::system_error const&)
    {
        CloseHandle(m_stop);
        m_stop = nullptr;
        OutputDebugStringW(L"DisplayHDR automation pipe could not start.\n");
    }
}

AutomationPipe::~AutomationPipe()
{
    if (m_stop) SetEvent(m_stop);
    if (m_thread.joinable()) m_thread.join();
    if (m_stop) CloseHandle(m_stop);
}

std::wstring AutomationPipe::Name() const
{
    return L"\\\\.\\pipe\\DisplayHDRTest-v1.2-" + std::to_wstring(GetCurrentProcessId());
}

bool AutomationPipe::Transfer(HANDLE pipe, bool reading, void* buffer, DWORD size, DWORD& transferred)
{
    OVERLAPPED operation = {};
    operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!operation.hEvent) return false;
    BOOL done = reading ? ReadFile(pipe, buffer, size, &transferred, &operation)
        : WriteFile(pipe, buffer, size, &transferred, &operation);
    if (!done && GetLastError() == ERROR_IO_PENDING)
    {
        HANDLE events[] = { m_stop, operation.hEvent };
        if (WaitForMultipleObjects(2, events, FALSE, 10000) == WAIT_OBJECT_0 + 1)
            done = GetOverlappedResult(pipe, &operation, &transferred, FALSE);
        else
        {
            CancelIoEx(pipe, &operation);
            GetOverlappedResult(pipe, &operation, &transferred, TRUE);
            done = FALSE;
        }
    }
    CloseHandle(operation.hEvent);
    return done && transferred != 0;
}

void AutomationPipe::Run()
{
    while (WaitForSingleObject(m_stop, 0) == WAIT_TIMEOUT)
    {
        HANDLE pipe = CreateNamedPipeW(Name().c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED
            | FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT
            | PIPE_REJECT_REMOTE_CLIENTS, 1, 65536, 16384, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) return;
        OVERLAPPED connection = {};
        connection.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!connection.hEvent) { CloseHandle(pipe); return; }
        BOOL connected = ConnectNamedPipe(pipe, &connection);
        if (!connected)
        {
            DWORD error = GetLastError();
            if (error == ERROR_PIPE_CONNECTED) connected = TRUE;
            else if (error == ERROR_IO_PENDING)
            {
                HANDLE events[] = { m_stop, connection.hEvent };
                connected = WaitForMultipleObjects(2, events, FALSE, INFINITE) == WAIT_OBJECT_0 + 1;
                DWORD ignored;
                if (connected) connected = GetOverlappedResult(pipe, &connection, &ignored, FALSE);
                else { CancelIoEx(pipe, &connection); GetOverlappedResult(pipe, &connection, &ignored, TRUE); }
            }
        }
        CloseHandle(connection.hEvent);
        if (connected)
        {
            std::string incoming;
            char buffer[4096];
            DWORD count;
            while (Transfer(pipe, true, buffer, sizeof(buffer), count))
            {
                incoming.append(buffer, count);
                if (incoming.size() > 16384) break;
                size_t newline;
                bool failed = false;
                while ((newline = incoming.find('\n')) != std::string::npos)
                {
                    auto request = std::make_shared<Request>(incoming.substr(0, newline));
                    incoming.erase(0, newline + 1);
                    if (!request->completed) { failed = true; break; }
                    {
                        std::lock_guard<std::mutex> lock(m_mutex);
                        m_request = request;
                        m_available = true;
                    }
                    HANDLE events[] = { m_stop, request->completed };
                    DWORD waited = WaitForMultipleObjects(2, events, FALSE, 5000);
                    {
                        std::lock_guard<std::mutex> lock(m_mutex);
                        if (waited != WAIT_OBJECT_0 + 1) request->cancelled = true;
                        if (m_request == request) { m_request.reset(); m_available = false; }
                    }
                    if (waited != WAIT_OBJECT_0 + 1) { failed = true; break; }
                    request->output += '\n';
                    size_t sent = 0;
                    while (sent < request->output.size())
                    {
                        if (!Transfer(pipe, false, &request->output[sent],
                            static_cast<DWORD>(request->output.size() - sent), count))
                        { failed = true; break; }
                        sent += count;
                    }
                    if (failed) break;
                }
                if (failed) break;
            }
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}

void AutomationPipe::Poll(Game& game)
{
    if (!m_available && !m_applying) return;
    std::lock_guard<std::mutex> lock(m_mutex);
    auto request = m_applying ? m_applying : m_request;
    if (!request) return;
    if (request->cancelled && !request->started) return;
    std::wstring id;
    try
    {
        JsonObject input = JsonObject::Parse(winrt::to_hstring(request->input));
        if (input.HasKey(L"id")) id = String(input.GetNamedValue(L"id"));
        Require(id.size() <= 128, "Request id is too long.");
        Require(input.HasKey(L"version") && Number(input.GetNamedValue(L"version"), 1, 1) == 1,
            "Protocol version must be 1.");
        Require(input.HasKey(L"command"), "Missing command.");
        auto command = String(input.GetNamedValue(L"command"));
        for (auto const& entry : input)
            Require(entry.Key() == L"id" || entry.Key() == L"version" || entry.Key() == L"command"
                || (command == L"set_state" && (entry.Key() == L"test" || entry.Key() == L"settings"
                    || entry.Key() == L"restart")), "Unknown request field.");
        JsonObject response;
        Put(response, L"version", 1.0);
        Put(response, L"id", id);
        Put(response, L"ok", true);
        if (command == L"catalog") response.SetNamedValue(L"catalog", game.AutomationCatalog());
        else if (command == L"get_state") response.SetNamedValue(L"state", game.AutomationState());
        else if (command == L"set_state")
        {
            if (!request->started)
            {
                game.QueueAutomationState(input, id);
                request->started = true;
                m_applying = request;
                return;
            }
            if (game.AutomationPending()) return;
            response.SetNamedValue(L"state", game.AutomationState());
        }
        else throw Error(L"unknown_command", "Unsupported command.");
        request->output = winrt::to_string(response.Stringify());
    }
    catch (Error const& error)
    {
        request->output = winrt::to_string(Failure(id, error.code.c_str(), std::wstring(winrt::to_hstring(error.what()))).Stringify());
    }
    catch (winrt::hresult_error const&)
    {
        request->output = winrt::to_string(Failure(id, L"invalid_json", L"Invalid JSON or field type.").Stringify());
    }
    catch (std::exception const&)
    {
        request->output = winrt::to_string(Failure(id, L"internal_error", L"Request could not be processed.").Stringify());
    }
    SetEvent(request->completed);
    if (m_request == request) m_request.reset();
    m_available = m_request != nullptr;
    m_applying.reset();
}
