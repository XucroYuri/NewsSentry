/**
 * ErrorBoundary — 渲染级错误捕获，防止单个组件崩溃导致整个管理后台白屏。
 *
 * 使用 React class component（Error Boundary 必须用 class），
 * 封装滚动页面不可恢复的错误并显示友好降级页面。
 */

import { Component, type ErrorInfo, type ReactNode } from "react"
import { AlertTriangleIcon, RefreshCwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface ErrorBoundaryProps {
  children: ReactNode
  /** 可选的降级回退组件（默认显示通用错误卡片） */
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(
      "[Admin ErrorBoundary]",
      error.message,
      "\nComponent stack:",
      info.componentStack?.slice(0, 500),
    )
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="flex min-h-[60vh] items-center justify-center p-6">
          <Card className="w-full max-w-md">
            <CardHeader className="text-center pb-4">
              <AlertTriangleIcon className="mx-auto mb-3 h-10 w-10 text-destructive" />
              <CardTitle>页面加载异常</CardTitle>
              <p className="text-sm text-muted-foreground">
                该模块发生了未处理的渲染错误，您可以尝试恢复。
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {this.state.error && (
                <div className="rounded-md bg-muted px-3 py-2">
                  <code className="text-[11px] text-destructive break-all select-text">
                    {this.state.error.message || "未知错误"}
                  </code>
                </div>
              )}
              <div className="flex gap-2 justify-center">
                <Button variant="outline" size="sm" onClick={this.handleReset}>
                  <RefreshCwIcon className="h-3.5 w-3.5" />
                  重试
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.location.reload()}
                >
                  刷新页面
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
